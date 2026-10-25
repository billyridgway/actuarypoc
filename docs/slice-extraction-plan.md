# Slice-Based Extraction: Plan

Status: implemented on branch `slice-extraction` (base `main` @ 41a14384).
Companion to `ARCH.md`; this document covers only the extraction front end.

## 1. Problem

Every LLM extractor in `src/actuarypoc/extract/` feeds the model the same
way: assemble a filing's raw page text, truncate it to the first 50,000
characters, and make **one** call that must return one JSON payload:

- `extract/mechanics_extractor.py` — `text[:50000]`, one call.
- `extract/assumptions_extractor.py` — `text[:50000]`, one call
  (`extract_assumption_set_from_text` passes the text untruncated today,
  but the per-product wrapper truncates the corpus to 50,000 chars first,
  and `extract_product_metadata_from_text` truncates to `text[:50000]`).
- `extract/assumptions_for_product.py` / `extract/mechanics_for_product.py`
  — combined multi-document text truncated to `max_chars=50000`.

A real SERFF filing runs to several hundred pages (several hundred
thousand characters). The current design therefore never shows the model
roughly 90% of a filing, flattens tables into prose, and has no notion of
where in the document a fact came from beyond what the model volunteers.

Separately, the workspace analyze route (`ui/server.py`) never calls the
extractors at all: its snapshot is a canned Promise-UL baseline plus a
small set of deterministic regex overlays.

The back half of the system is **not** the problem and does not change
shape: product-line models with per-field `EvidenceRef`
(document/page/snippet/confidence) and status, requirements
classification, gaps, capability assessment, feature requests, and trust
levels, all persisted as objects.

## 2. Design overview

Replace blob-and-truncate feeding with three mechanisms, all
object-native and memory-bounded:

1. **Document map + slices** — at analysis time each document is reduced
   to a *map*: its full text partitioned into page-anchored slices. The
   map and the slice texts are stored as objects next to the document's
   existing workspace artifacts. No pipeline pass ever holds a whole
   filing's text plus more than one slice, and no pass joins slice texts
   back into a full-text copy.
2. **Slice-fed extraction** — the mechanics, assumptions, and metadata
   extractors are dispatched per slice (sequentially, in document
   order) and their per-slice results are merged into exactly the output
   types they return today (`List[ProductMechanic]`, `AssumptionSet`,
   metadata `dict`). The 50,000-char truncation disappears everywhere.
3. **Deterministic table channel** — tables are lifted out of the PDF as
   structured grids by `pdfplumber`, with page provenance. The model
   never transcribes numbers (parse-don't-generate). This channel makes
   no LLM calls.

The workspace analyze route then runs all three over the workspace's
uploaded documents and merges the results into the snapshot
(additively — see §6).

## 3. Document map and slices

New module: `src/actuarypoc/extract/document_map.py`.

**Canonical text.** A document's canonical text is its page texts joined
by `"\n"` — the same convention `read_document_text` already uses. All
character offsets refer to the canonical text. Pages are 1-based.

**`DocumentSlice`** (frozen dataclass):

| field | meaning |
|---|---|
| `slice_id` | `{doc_slug}-s{index:04d}` |
| `doc_id` | caller-supplied document identifier |
| `document_hint` | filename/label for evidence citations |
| `page_start`, `page_end` | 1-based pages the slice spans (inclusive) |
| `heading` | heading line that opened the slice, or `None` |
| `char_start`, `char_end` | half-open range in the canonical text |
| `text` | the slice text itself |

**`DocumentMap`**: `doc_id`, `document_hint`, `object_path`, `page_count`,
`total_chars`, and the slice descriptors (same fields minus `text`).
Serializes to/from plain dicts for object storage.

**Building.** `build_document_map(doc_id, document_hint, pages, ...)`
consumes `pages` as a lazy iterable of per-page strings (e.g. a
generator over `PdfReader.pages[i].extract_text()`), so peak extra
memory is one page plus the current slice buffer plus the finished slice
texts of *this one document* — documents are processed one at a time and
their slice lists are released before the next document starts.

**Heading heuristics** (deterministic, conservative). A line opens a new
section when, stripped, it is:

- ALL-CAPS (≥4 chars, contains a letter, no lowercase), ≤ 90 chars; or
- matches `^(SECTION|ARTICLE|PART|CHAPTER|APPENDIX|EXHIBIT|SCHEDULE)\b`
  case-insensitively; or
- a numbered heading `^\d+(\.\d+)*\.\s+\S` of ≤ 90 chars.

A heading only forces a cut when the current slice already holds
≥ 200 chars (avoids heading-shrapnel slices).

**Slicing.** Lines accumulate into the current slice. A cut happens when
(a) a heading line starts a new slice, or (b) the slice reaches
`target_chars` (default 4,000) at a line boundary. A slice never exceeds
`max_chars` (default 6,000): a single over-long line is hard-cut. When a
slice is cut by size (not by heading), the next slice repeats the last
`overlap_chars` (default 300) of text, so a fact straddling a boundary
appears whole in at least one slice. A trailing slice shorter than
`min_chars` (default 800) is merged into its predecessor.

**Coverage invariant** (tested): the union of `[char_start, char_end)`
over all slices equals `[0, total_chars)` — every character of the
document belongs to at least one slice. This is the property the old
pipeline lacked past char 50,000.

**Storage** (additive keys, written at analyze time):

- `workspaces/{ws}/analysis/documents/{doc_slug}/map.json` — the map.
- `workspaces/{ws}/analysis/documents/{doc_slug}/slices.json` — slice
  texts with their descriptors.
- `workspaces/{ws}/analysis/documents/{doc_slug}/tables.json` — table
  artifacts (§5).

## 4. Slice-fed extraction

New module: `src/actuarypoc/extract/slice_extraction.py` (merge +
dispatch); the existing extractor modules gain `*_from_slices` entry
points whose per-call cores are the *same* prompt/parse code the
single-call functions use today (refactored into `_…_single_call`
helpers, so output shape cannot drift between modes).

**Dispatch.** Units are slices, dispatched sequentially in document
order. Consecutive slices may be grouped into one call up to
`dispatch_char_budget` (default 6,000 chars ≈ at most two slices). Every
slice is in exactly one unit: dispatch is never a sample. Each unit's
text block is framed with explicit provenance headers
(`[SLICE {slice_id} | {document} | pages {a}–{b} | heading: …]`).

**Evidence re-anchoring (mechanics).** Model-supplied `page` values are
not trusted. For each returned `FilingSource` with a snippet, the
snippet is located inside the dispatch unit's slices (whitespace-
normalized substring match, then a ≥0.75 token-overlap fallback — the
same approach as `ui/server.py:_find_workspace_evidence`). On a hit, the
source's `page` becomes the exact 1-based page containing the match and
`document_hint` the real document name. On a miss, `page` becomes the
unit's page span (`"pp. a–b"`) and confidence is multiplied by 0.7. A
mechanic returned with no sources gains one deterministic anchor source
(page span + the unit's first 160 chars, confidence 0.5). Citations in
merged output therefore always resolve to real pages of the real
document.

**Merge rules — mechanics** (`merge_mechanics`):

1. Pass 1, by normalized id (lowercase, non-alphanumerics collapsed to
   `_`): instances merge — `filing_sources` concatenated and deduped by
   (document_hint, page, normalized snippet); `confidence` = max;
   `upstream_ids`/`downstream_ids` = order-preserving union;
   `description` = the one from the highest-confidence instance (ties:
   longest).
2. Pass 2, by (normalized name, type): folds same-name/same-type
   mechanics the model id'd differently into the first-seen instance
   (whose id wins if it has ≥ as many sources, else the other's).
3. Output order is first-seen document order; `product_code` is forced
   to the target code; `source`/`status` stay `ai_extracted`/`candidate`.

**Merge rules — metadata** (`merge_metadata`): field-wise, the first
non-null value in document order wins; the winning unit's page span is
recorded per field in a provenance side-dict. A later, different non-null
value is recorded as a conflict (field, kept value, rejected value,
page span) in the run report — never silently overwritten.

**Merge rules — assumptions** (`merge_assumption_sets`): each unit
yields one `AssumptionSet`. Fields merge first-non-empty in document
order, except `description`, which comes from the most complete unit
(most populated fields). `id` and `product_code` are forced to the
requested values; `status` is forced to `draft`, `is_current` to
`False`. Field conflicts go to the run report.

**Failure isolation.** A unit whose call or parse fails is recorded
(`failed_units` with the error) and dispatch continues with the next
unit. A part (metadata / mechanics / assumptions) is `ok` when ≥1 unit
succeeded and none failed, `partial` when some failed, `failed` when
all failed or the part raised before dispatch.

**`from_text` functions.** `extract_mechanics_from_text`,
`extract_assumption_set_from_text`, and
`extract_product_metadata_from_text` keep their signatures but are
reimplemented over page-less window slices built from the supplied text
(same slicing parameters; page = `None`, evidence cites the char range).
No truncation remains anywhere.

**Per-product wrappers.** `generate_mechanics_for_product` and
`generate_assumption_set_for_product` /
`generate_product_metadata_from_minio` gain `use_slices: bool = True`.
In slice mode a new loader streams each discovered document from MinIO
and yields its pages (no join, no truncation) → maps → slice extractors.
The legacy blob path remains available behind `use_slices=False` as an
explicit A/B and rollback valve while slice mode is new — it is the
baseline in the discriminating acceptance (§8). It should be deleted
once slice mode has soaked in production use.

## 5. Deterministic table channel

New module: `src/actuarypoc/extract/table_extractor.py`; adds
`pdfplumber` to `requirements.txt`.

For each PDF page, strategies are tried in order — `lines`,
`lines_strict`, then `text` — and the first strategy yielding at least
one *accepted* table wins for that page; the strategy used is recorded
in provenance. Acceptance gates keep the channel honest: any table
needs ≥2 rows and ≥2 columns, and a `text`-strategy table (no ruling
lines) must additionally pass a data-grid gate — consistent column
count and numeric cells clustered in a consistent column across most
rows — because the text strategy otherwise chops ordinary prose
paragraphs into fake columns. A page whose only "tables" fail the
gates yields no artifacts. Each table becomes a `TableArtifact` dict:

```json
{
  "id": "sha1(document|page|index|first-row)[:12]",
  "document": "filing.pdf",
  "objectPath": "workspaces/{ws}/…/filing.pdf",
  "page": 31,
  "indexOnPage": 0,
  "title": "ANNUAL PREMIUM RATES PER $1,000 OF FACE AMOUNT",
  "columns": ["Age", "Preferred Non-Tobacco", "…"],
  "rows": [["25", "1.42", "…"]],
  "rowCount": 5, "columnCount": 4,
  "provenance": {"engine": "pdfplumber", "strategy": "lines"}
}
```

- `title` is the nearest preceding non-empty text line on the same page
  (within the text above the table's bounding box), else `null`.
- `columns` is the first row when it looks like a header (≥ half its
  cells non-numeric); those cells are then excluded from `rows`.
  Otherwise `columns` is `[]` and every row is in `rows`.
- Cell values are the extracted strings, stripped — byte-for-byte what
  the PDF's text layer carries. The model is never asked to read a table
  and never transcribes a number.
- This channel coexists with, and does not change, the UL
  executable-mechanics extraction (`extract/workspace_ul_mechanics.py`),
  which remains the path for accepted COI/surrender schedules. The
  generic channel provides provenance grids for arbitrary tables.

## 6. Workspace wiring

New module: `src/actuarypoc/extract/slice_pipeline.py`, one entry point
`run_workspace_slice_extraction(workspace_id, documents) -> dict`
returning snapshot additions. `api_workspace_analyze` calls it after
`_apply_workspace_document_evidence` and before the projection /
reconcile / understanding builders, so downstream views see the new
facts.

Per workspace document (PDFs only; others are recorded as skipped):

1. Stream the object from MinIO; build the map from a lazy page
   iterator; store `map.json` + `slices.json`.
2. Run the table channel over the bytes; store `tables.json`.

Per workspace (after all documents): metadata → mechanics → assumptions
over the union of slices (document order), with product code = the
metadata-extracted code when present, else the snapshot's product code.

**Snapshot additions (additive keys only; no existing key changes
shape):**

- `sliceExtraction` — run report: overall status
  (`ok|partial|failed|skipped`), model, timing, call counts, per-part
  status, per-document coverage (`slicesDispatched`/`slicesTotal`),
  failed units, and metadata conflicts.
- `documentMaps` — per-document map descriptors + storage keys.
- `extractedTables` — all table artifacts (grids included).
- `extractedMechanics` — merged mechanics as dicts.
- `extractedAssumptionSet` — merged set as dict, or `null`.

**`extractedFacts` merge.** Fact dicts keep today's shape
(`label/value/source/confidence/status/provenanceKind`):

- For `Carrier`, `Filing context`, `Product name`, `Product code`,
  `Product type`: when the existing fact's value is empty, it is filled
  from slice metadata (`status: "extracted"`,
  `provenanceKind: "slice_extraction"`,
  `source: "{document} p. {page}"`, confidence from provenance).
  When the existing fact already carries a *different* non-empty value
  (e.g. the canned Promise-UL identity), it is **not** overwritten; the
  document-derived value and its conflict are recorded under
  `sliceExtraction.conflicts` instead. The snapshot never silently
  mixes two identities.
- Two facts are appended: `Extracted mechanics` (value: merged mechanic
  names) and `Extracted tables` (value: table titles), each sourced to
  the slice run / table channel with page-bearing provenance in the
  corresponding snapshot sections.

**`productUnderstanding`** gains, additively and only when known:
`carrier` and `filingContext` (from the merged facts) and
`sliceExtractionStatus`.

## 7. Failure and fallback behavior

| failure | behavior |
|---|---|
| `OPENAI_API_KEY` unset | model parts `skipped` with reason; map + tables still run; analyze succeeds |
| one dispatch unit fails | unit recorded; part `partial`; other units' results still merged |
| all units of a part fail | part `failed`; snapshot section present with the error; analyze succeeds |
| a document is not a PDF / unreadable | recorded per-document `skipped`/`failed`; other documents continue |
| slice stage raises unexpectedly | caught at the analyze boundary; `sliceExtraction.status = "failed"` with the error; the canned snapshot still builds and persists |
| no tables found | `extractedTables: []`, part status `ok` with `tableCount: 0` |

Nothing in this stage can fail the analyze route, and nothing is faked:
a part that did not run says so, with the reason, in the snapshot.

## 8. Verification

- Repo suite: `PYTHONPATH=src pytest` must not regress. (Note: the
  suite is *not* green at the base commit — 8 failures pre-exist at
  41a14384, verified by running the base tree: 111 passed / 8 failed.
  This branch: 128 passed / the same 8 failed, i.e. zero regressions
  and 17 new passing tests.)
- New tests (`tests/test_slice_extraction.py`,
  `tests/test_table_extractor.py`): slicing coverage over a >50,000-char
  document (every char in ≥1 slice; slices bounded; page anchoring),
  heading cuts, merge dedupe/conflict behavior, evidence re-anchoring,
  table extraction exactness against a generated ruled-table PDF, and an
  end-to-end `run_workspace_slice_extraction` + analyze run over a long
  document with a fake OpenAI client and a fake MinIO.
- Discriminating acceptance: a synthetic filing of >60,000 chars whose
  identity facts (carrier, product code, filing id) and premium-rate
  table exist **only after** char 50,000.
  - Old path: the captured prompt provably excludes the late text
    (offsets > 50,000 vs `text[:50000]`), so the late facts/table are
    invisible to it.
  - New path: `extractedFacts` carry the late facts with correct page
    citations, and the extracted table matches ground truth
    cell-for-cell.
- Deployed acceptance: the branch image rolled into the `actuarypoc`
  namespace; a new workspace + the long synthetic + analyze; the stored
  snapshot shows the late-document facts. The pre-existing smoke
  workspace `ws-92e574c9` is left untouched.

## 9. Model reality note

Slice dispatch multiplies model calls (one per ≤6,000 chars instead of
one per filing). Against the currently deployed facade model
(`roost-ep-2c1ba0ed6f77`, qwen2.5-3b on CPU) the run report records call
counts, per-part latency, and parse outcomes verbatim; if the small
model cannot hold the JSON shape or the latency is unusable, that is
reported as a model limit with numbers — the deterministic parts (map,
tables, wiring, fallback) stand on their own, and the merge/dispatch
machinery is model-agnostic.
