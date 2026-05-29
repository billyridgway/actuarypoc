# Developer Setup – ActuaryPOC

This repo is meant to be exercised from a local Python environment and the
Raspberry Pi k3s cluster. These steps give you a repeatable way to:

- create a virtualenv
- install dependencies
- install `actuarypoc` as a package
- run tests
- run the project health CLI.

## 1. Prerequisites

- Python 3.9+ installed (`python3 --version`)
- `git` installed
- Optional but recommended:
  - `kubectl` configured to talk to the k3s cluster
  - access to the repo root (this folder)

You do **not** need MinIO or k3s locally just to run unit tests, but you do
for full end-to-end checks.

## 2. Create and activate a virtual environment

From the `actuarypoc` repo root:

```bash
cd actuarypoc
python3 -m venv .venv
source .venv/bin/activate
```

On Windows (PowerShell), this would be:

```powershell
cd actuarypoc
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## 3. Install dependencies

Install the runtime dependencies:

```bash
pip install -r requirements.txt
```

Install dev/test tools (pytest) and the package itself in editable mode so
`import actuarypoc` works during tests:

```bash
pip install pytest
pip install -e .
```

After this, `python -m actuarypoc...` and tests importing `actuarypoc.*`
should work inside the virtualenv.

## 4. Run tests

To run the full test suite:

```bash
pytest -q
```

To run just the health_check tests:

```bash
pytest src/actuarypoc/tests/test_health_check.py -q
```

These tests do **not** require a real k3s cluster; they only exercise the
aggregation logic and serialization.

## 5. Run the health CLI

With the virtualenv active and `kubectl` configured, you can run the project
health CLI:

```bash
python -m actuarypoc.tools.health_check \
  --kubeconfig ../.kube/pi-k3s.yaml \
  --namespace illustrations-poc \
  --minio-namespace minio-system \
  --ui-url http://192.168.50.251:30301/health
```

Use `--json` for machine-readable output:

```bash
python -m actuarypoc.tools.health_check --json
```

The CLI only uses `kubectl`, the UI `/health` endpoint (if provided), and a
best-effort MinIO connectivity check. It does **not** print secrets or raw
PAS/projection data.

## 6. Deactivating the virtualenv

When you’re done:

```bash
deactivate
```

You can reactivate later with:

```bash
cd actuarypoc
source .venv/bin/activate
```

This setup is intended to be reused for future work in this repo so that
tests, CLIs, and tooling behave consistently.
