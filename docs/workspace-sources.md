# Workspace sources: reference objects in the store, don't copy them

Status: built with the object-store source picker (Oct 2026). This doc is
the design the picker was built to; where the code and this doc disagree,
the code is what runs and this doc should be corrected.

## Why

A workspace used to be populated only by uploading files. The upload is
stored under the workspace's own prefix, so the same filing ended up in
the store once per workspace that used it — on top of wherever it already
lived (a Drive folder, a knowledge collection's corpus bucket, a carrier
filing library). Copies drift; provenance gets murky; bulk use (a whole
bucket of filings) is impractical.

On Roost the filings already live in the object store. A workspace should
*point at* them.

## The model

A workspace document is one of two kinds:

* **Uploaded** (`kind: "workspace"`) — the pre-picker behavior, unchanged.
  Bytes live at `workspaces/{id}/{timestamp}_{filename}` in the app
  bucket; the document record carries `object_path`.
* **Source-referenced** (`kind: "object_store"`) — the document record
  carries a `source` object and *no copied bytes*:

  ```json
  "source": {
    "bucket": "kb-kb-4188198d",
    "key": "gdrive:15vtwcnfbkqkBa7h8c2-sDMe9k7XbYmOy",
    "etag": "<etag pinned at selection>",
    "size": 760849,
    "lastModified": "2026-10-25T19:41:03Z",
    "selectedAt": "2026-10-26T11:20:00Z",
    "analyzedEtag": "<etag actually read at the last analyze>",
    "changedAtAnalyze": false
  }
  ```

  `object_path` mirrors the source key (it names the object the document
  reads); the bytes are always fetched from `source.bucket` /
  `source.key` at analyze time through the app's S3 client.

Derived artifacts (document maps, slices, tables, equation artifacts)
are unchanged: they live under the workspace's own prefix, and their
provenance cites the source `bucket` + `key` + page — so an equation's
evidence points at the object in the store, not at a workspace copy.

Deleting a workspace deletes only objects under its own prefix.
Source-referenced objects are never deleted by workspace deletion (the
delete path already skips object paths outside the workspace prefix,
and it never touches other buckets).

## Pin, stale, never silent

Selection **pins** the object's etag at selection time.

* At **analyze** time each source is `stat`-ed again. If the current
  etag differs from the pin, analyze proceeds with the current content,
  and the change is recorded three ways: on the document record
  (`changedAtAnalyze: true`, the pin is advanced to the etag actually
  read, which is also recorded as `analyzedEtag`), in the snapshot's
  document record for that analyze, and in the workspace change history
  (`kind: "source_changed"`). Nothing is ever silently re-read: the
  cited etag is always the etag whose bytes produced the artifacts.
* **Between** analyzes, `GET /api/workspaces/{id}` exposes each source's
  `changedSinceAnalyzed` (a cheap stat/etag comparison against
  `analyzedEtag`, or the pin if never analyzed; `null` when the check
  itself fails, with the object reported missing when it is gone). The
  remedy offered is re-analyze.
* Adding sources to an already-analyzed workspace marks its projection
  stale (the existing convention) and records `kind: "sources_added"`
  in the change history.

## API

Browsing (uses the app's configured S3 client):

* `GET /api/object-store/buckets` → `{buckets: [{name, createdAt}]}`
* `GET /api/object-store/objects?bucket=&prefix=&recursive=` →
  `{bucket, prefix, entries: [{key, isPrefix, size, lastModified, etag}],
  truncated}`. Non-recursive listing is one level (files + sub-prefixes)
  for navigation; a page is capped at 500 entries and `truncated` says
  so when there are more. `recursive=true` enumerates files under the
  prefix, capped at 1000.

Workspace sources:

* `POST /api/workspaces` accepts an optional body
  `{sources: [{bucket, keys: [...]}, {bucket, prefix: "..."}]}`.
  A prefix selection resolves to its concrete object list **at
  creation** (recursive, cap 1000 — beyond that the request is a 400);
  the resolved keys + etags are what get recorded. Selections are
  resolved and validated *before* the workspace is created, so a bad
  key fails the request without leaving an empty workspace behind.
* `POST /api/workspaces/{id}/sources` — same body shape; adds sources
  after creation. Re-selecting an object already referenced
  (same bucket + key) is a no-op reported in `skippedDuplicates`.
* `GET /api/workspaces/{id}` gains a top-level `sources` array
  (per-source state as above) and each entry in `documents` gains the
  document's `source` object when it is source-referenced.
  Upload-created workspaces have `sources: []` and behave exactly as
  before.

## Identity — stated honestly

Browsing and reading use **the app's configured S3 credentials**. The
deployed POC is single-tenant and unauthenticated; whoever can reach
the app can browse whatever that one identity can reach, and Roost's
account scoping decides what that is (an identity sees its own
account's buckets; other accounts' buckets answer `NoSuchBucket`).

The integration point for the real model is named, not faked: when the
app carries the signed-in user's Roost identity (the session/STS flow
the Roost UI already uses), the browsing endpoints pass that identity
through, and listing scopes to the buckets that identity's OU can read —
the nest IAM model already supports OU-scoped bucket visibility and
cross-OU read grants via roles. Until then, per-user scoping does not
exist in this app and this design does not pretend otherwise.

Consequence observed at build time (Oct 2026): the knowledge
collection's corpus bucket (`kb-kb-4188198d`, keys `gdrive:<id>`) is
owned by a different account than the app's, so the app's identity
cannot list or read it today. Making a collection pickable by the app
is an identity grant decision on the Roost side, not something the
picker can route around honestly.

## What does not change

* Upload remains as the off-Roost fallback, byte-for-byte the old flow.
* The analyze pipeline (maps, slices, tables, extractors, equations)
  consumes the same document records; only byte-fetching learned to
  resolve a document's bucket from its `source` when present.
* Harvest reads slices from the snapshot's `documentMaps` exactly as
  before — source-built workspaces produce those maps identically,
  which is the point: the ws-92e574c9 failure mode (no maps → harvest
  reads nothing) cannot occur for a workspace whose documents came
  through analyze, whatever their origin.
