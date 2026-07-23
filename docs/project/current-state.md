# Current implemented state

Evidence captured 2026-07-22 from the local repositories and Pi k3s cluster.
This is a snapshot, not a roadmap.

## Verified in the repository

- `actuarypoc` contains a Python projection and assumptions backend, product
  DSLs, MinIO and Postgres integration, a FastAPI API, and a React/Vite UI.
- The API exposes product catalog, workspace/document analysis, product review,
  ProductDefinition, requirements/evidence, illustration, decisions/bundles,
  assumptions, mechanics, projection listing, and run-detail surfaces.
- Shared life-product models and capability/requirements classification exist.
  Product-specific examples and compatibility routes still exist, notably
  P12TRF; product agnosticism is therefore an ongoing constraint, not a proven
  property of the whole codebase.
- AI-backed entry points exist for summaries, assumption discovery/generation,
  scenarios, and mechanics. The repository also contains configured, fixture,
  cached, fallback, and mechanically derived paths. Each output must retain an
  honest provenance classification; the presence of an AI endpoint alone is
  not proof that a particular result came from a model call.
- Python tests cover projection/audit fundamentals, product registry, shared
  life models and capabilities, requirements classification, health checks,
  workspaces, and selected API paths. A P12TRF golden test exists.
- Playwright tests currently cover a Promise UL workspace flow. The web package
  has build and E2E commands but no generic unit-test script.
- `illustration-operator` is a Go controller that reconciles
  `IllustrationProject` resources into extraction/projection Jobs and status,
  using product configuration from a ConfigMap.
- GitHub Actions builds multi-architecture `actuarypoc` images on selected
  branches and an arm64 operator image on `main`. These workflows build and
  push; repository evidence did not show a comprehensive test job.

## Verified live on 2026-07-22

- Namespace `illustrations-poc` has ready `projection-ui` and
  `illustration-operator` deployments.
- `projection-ui` runs `ghcr.io/billyridgway/actuarypoc:main` with image ID
  `sha256:47570d28dcff16b23ade16edc0b4cf372a1b56838d80836809807b8e11bfeb96`.
  Its `/health` build metadata reports Git SHA
  `1fc1d4c0c31f38f26dc81984d3cad6c65b0ad30c`, build time
  `2026-07-01T03:28:49Z`, and HTTP 200.
- The operator runs `ghcr.io/billyridgway/illustration-operator:main`.
- Historical P12TRF extraction and illustration Jobs are complete.
- Postgres is degraded: its deployment reports `0/1`; a replacement pod is
  Pending and an older pod is Terminating. Database-dependent workflows are
  not currently proven healthy. During validation, `/api/products` timed out
  from inside the UI pod while `/health` succeeded.

## Not established by this snapshot

- The local `actuarypoc` checkout has pre-existing uncommitted product-code and
  test changes. They are not claimed as deployed.
- A mutable `:main` tag alone does not establish which Git commit is running;
  closeout must retain both the pulled digest and `/health` build identity.
- Current end-to-end behavior for every product, AI path, decision bundle, and
  responsive UI workflow was not exercised during this documentation-only task.
- Memory and older validation notes describe additional completed work; those
  remain historical until reconfirmed against source and runtime.
