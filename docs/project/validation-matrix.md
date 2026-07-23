# Test and validation matrix

Run `scripts/actuary-verify help` from the workspace root for the canonical
entry points. Commands intentionally distinguish local proof from live proof.

| Change surface | Minimum local proof | Additional proof |
| --- | --- | --- |
| Python domain/extraction/projection | `focused -- <pytest targets>` then `full-local` | golden/differential products; AI integrity where applicable |
| FastAPI/API contract | focused API tests then `full-local` | source-blind calls against live service |
| React/UI | web build plus focused Playwright spec | live rendered workflow, screenshots, UI review |
| Shared product/workspace/evidence code | focused + full local | `product-agnosticity`; justify every product reference |
| AI-dependent behavior | focused + full local | `ai-integrity`; materially different inputs and processing evidence |
| Operator/CRD/config | `go test ./...`, `go build ./...` | live reconciliation/status/Job workflow |
| Deployment/config | syntax/build checks | `live`; rollout, digest/source identity, health, APIs, workflow |
| Internal docs/instructions | link/path and command no-op checks | no product deployment required |

Canonical commands:

```bash
scripts/actuary-verify focused -- <pytest targets or other focused command>
scripts/actuary-verify full-local
scripts/actuary-verify live
scripts/actuary-verify product-agnosticity
scripts/actuary-verify ai-integrity
```

`product-agnosticity` is an inventory gate, not an automatic accusation: each
reported reference needs an explicit scoped justification or removal.
`ai-integrity` performs deterministic structural checks; a changed AI feature
still requires a behavior contract with at least two materially different
inputs and captured runtime provenance.
