# Analysis slice consumption — speed + reuse (Oct 27, 2026)

Why: a 13-filing analysis spent ~16–18 minutes, most of it in the
`extracting_slices` phase — three model passes (product metadata,
mechanics, assumptions) dispatched one ~6,000-char unit at a time,
strictly sequentially, and every re-analysis re-read and re-extracted
every document even when nothing had changed. This note records the
five improvements that landed together. Slicing itself is unchanged
and deliberately retained: the product must stay portable to
on-prem hardware whose local models have smaller effective contexts,
so bounded units are more necessary there, not less. Everything
below is tuned by environment knobs, never by hardcoding
cloud-sized assumptions into the pipeline.

## 1. Parallel unit dispatch

`slice_extraction.py` now runs dispatch units on a bounded thread
pool (`_dispatch_units`). Concurrency resolves as: explicit argument
> `ACTUARYPOC_SLICE_DISPATCH_CONCURRENCY` > default **8**, clamped
to ≥ 1. The single-call cores build a fresh OpenAI client per call,
so they are thread-safe as-is.

**Determinism is a hard requirement, not a hope:** unit outcomes are
collected by unit index and folded in ORIGINAL unit order
(`_fold_outcomes`). The merges are order-sensitive (first-non-empty
wins, conflicts recorded), so a parallel run's merged artifacts —
mechanics, metadata + provenance + conflicts, assumption set +
conflicts — and every report field except timing are identical to a
sequential run over the same inputs. Per-unit failure isolation is
unchanged: a failing unit lands in `failed_units` (in unit order),
the rest still merge, and status stays honest (`partial` / `failed`).
Covered by `test_slice_consumption.py` (parallel-vs-sequential on
the long synthetic filing for all three passes, with a
content-hashed delay scrambling completion order; a two-failure
isolation case run both ways).

## 2. Larger dispatch units

Default dispatch budget 6,000 → **48,000 chars**
(`DEFAULT_DISPATCH_CHAR_BUDGET`; `ACTUARYPOC_SLICE_DISPATCH_CHARS`
still overrides). Slices themselves are unchanged (4,000 target /
6,000 max) — only the grouping of slices into model-call units
grows, so page provenance and coverage are untouched.

**Appliance note:** the on-prem profile sets
`ACTUARYPOC_SLICE_DISPATCH_CHARS` (and, if cores are scarce,
`ACTUARYPOC_SLICE_DISPATCH_CONCURRENCY`) back down to whatever the
local model handles well. The cloud defaults are not baked into any
other layer.

## 3. Unchanged-document reuse

`slice_pipeline.py` keys reuse on source etags — the etag the
workspace pins at selection, advanced to the etag actually read at
analyze time (`analyzedEtag`), falling back to a listing-based stat
of the object (the codebase avoids HEAD: some stores' HEAD breaks
the MinIO parser). A document with no trustworthy etag is never
reused on a guess.

- **Per document:** the stored artifacts (`map.json`, `slices.json`,
  `tables.json` under `workspaces/{id}/analysis/documents/{slug}/`)
  now record `sourceEtag`. When the current etag matches and all
  three artifacts exist, the document record is rebuilt from them —
  no download, no re-slice, no re-table-extract. A changed etag
  reprocesses only that document.
- **Whole run:** when every document has a trustworthy etag, the
  run's full result is cached at
  `workspaces/{id}/analysis/slice-run-cache.json` under a fingerprint
  of {dispatch budget, product-code hint, model-key presence,
  per-document etags}. A hit returns the cached result flagged
  `sliceExtraction.reused = true` with a fresh `duration_s`.

**Separability (verified in code):** the cache stores the pipeline's
*return value*. The analyze route consumes that value through exactly
the path a fresh run takes — snapshot merge, mechanics rebuild, and
the decision-state carry-over (`carry_over_decision_state`) all run
downstream of it, on it. Nothing about reuse bypasses the merge, so
approvals survive a cached re-analysis exactly as they survive a
fresh one; `test_cached_reanalysis_preserves_approvals_and_skips_model_calls`
proves it end-to-end (confirm all tables → re-analyze → zero new
model calls, all acceptances still in force). Per-document reuse
also feeds the same path: reused documents contribute their stored
slices to the union the three passes run over.

## 4. Paragraph-aware size cuts

`document_map.build_document_map`: when a size cut is due, the
grouping loop first looks back for a paragraph boundary — a blank
line whose end falls within ±800 chars of the 4,000-char target and
within the max — and cuts there, so slices end at paragraph ends
instead of mid-paragraph. The remainder of the group keeps
accumulating (no slice is forced short). When no break is in the
window, behavior is exactly the previous one (defer to the first
line boundary at or past the window, hard cap at max). All invariants
are preserved and tested: exact coverage of the canonical text,
max-chars boundedness, overlap seeding after size cuts, the
trailing-small-group merge.

## 5. Sub-progress

`run_workspace_slice_extraction` accepts a `progress_callback`
receiving `{stage, detail, documentsDone, documentsTotal, pass,
unitsDone, unitsTotal}` events — per document while reading
("Documents i of n read") and per completed unit in each pass
("Mechanics — unit d of t"). The analysis job threads it through:
the job record gains `phaseDetail` + `phaseProgress` (writes
throttled to ~1/sec within a stage/pass, immediate on change;
cleared on every terminal state). The Workbench analysis line and
the workspace page render the detail next to the phase label when
present. Progress is display-only — it never affects results.

## Tests

`src/actuarypoc/tests/test_slice_consumption.py` (13 tests):
parallel-vs-sequential determinism for all three passes,
failure isolation in both modes, the 48k default, paragraph-cut
preference + fallback with map invariants, whole-run reuse (zero
new model calls), changed-document reprocessing + re-caching,
per-document reuse in a mixed run, no-etag no-reuse, monotonic
progress counters, and the API-level cached-reanalysis approvals
test above. One pre-existing test was adjusted:
`test_mechanics_dispatch_covers_tail` pins its historical
6,000-char budget explicitly, since at the new 48k default its
filing is only two units and the many-unit merge it exists to
exercise would no longer occur.
