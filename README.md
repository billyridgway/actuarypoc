# ActuaryPOC Workspaces

ActuaryPOC is a document-first product-understanding workspace. The public
application now has one flow:

1. Create a workspace by selecting one or more filing documents.
2. Upload and review the documents attached to the workspace.
3. Run product analysis.
4. Review the resulting product-understanding snapshot.
5. Create and update workspace feature requests for unsupported capabilities.
6. Delete the workspace and its workspace-scoped documents when it is no
   longer needed.

Legacy product catalog, product review, projection viewer, illustration, and
debug surfaces are no longer exposed. Some projection and product-understanding
modules remain as internal implementation details of workspace analysis.
Workspace metadata, document manifests, analysis snapshots, and feature
requests are stored as JSON objects in MinIO alongside uploaded documents.

## Application surface

The React application is served at `/web`. `/` redirects there.

The public API is limited to:

- `POST /api/workspaces` — create an empty workspace.
- `GET /api/workspaces` — list workspaces.
- `GET /api/workspaces/{workspace_id}` — get metadata, documents, and the
  latest analysis snapshot.
- `DELETE /api/workspaces/{workspace_id}` — delete a workspace and its owned
  objects.
- `POST /api/workspaces/{workspace_id}/documents` — upload a document.
- `POST /api/workspaces/{workspace_id}/analyze` — analyze the workspace.
- `GET /api/workspaces/{workspace_id}/feature-requests` — list workspace
  feature requests.
- `POST /api/workspaces/{workspace_id}/feature-requests` — create a workspace
  feature request.
- `PATCH /api/workspaces/{workspace_id}/feature-requests/{id}` — update its
  status.
- `GET /ui/dev` — browse MinIO objects for operational diagnostics.
- `GET /api/dev/objects` and `GET /api/dev/object` — support the diagnostic
  object browser.
- `GET /health` — service health.

## Local development

Requirements: Python 3.11+, Node.js/npm, and MinIO.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

export MINIO_ENDPOINT=localhost:9000
export MINIO_ACCESS_KEY=minioadmin
export MINIO_SECRET_KEY=minioadmin
export MINIO_BUCKET=actuarypoc

uvicorn actuarypoc.ui.server:app --reload --port 8080
```

Workspace objects use the following durable layout:

```text
workspaces/{workspace_id}/workspace.json
workspaces/{workspace_id}/documents/{document_id}.json
workspaces/{workspace_id}/feature-requests/{request_id}.json
workspaces/{workspace_id}/{timestamp}_{uploaded_filename}
```

Enable bucket versioning and replicate or back up the bucket outside the
cluster for disaster recovery. Postgres remains an optional dependency of
legacy internal product-analysis helpers, but it is not required by the public
workspace flow.

In another terminal:

```bash
cd web
npm ci
npm run dev
```

For a production-style UI build:

```bash
cd web
npm ci
npm run build
```

## Validation

```bash
PYTHONPATH=src pytest
cd web && npm ci && npm run build
```
