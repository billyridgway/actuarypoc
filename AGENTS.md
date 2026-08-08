# Repository Instructions

## Post-merge deployment

After merging a pull request into `main`:

1. Watch the GitHub Actions workflow triggered by the merge commit until it
   reaches a terminal state.
2. If the workflow fails or is cancelled, report the failure and do not
   restart the deployment.
3. After the workflow succeeds and the `ghcr.io/billyridgway/actuarypoc:main`
   image has been pushed, restart `deployment/projection-ui` in the
   `illustrations-poc` namespace using:
   `/Users/advisor/.openclaw/workspace/.kube/pi-k3s.yaml`.
4. Wait for the Kubernetes rollout to complete.
5. Confirm the replacement pod is ready, report its immutable image digest,
   and verify `/health` responds successfully inside the pod.

Do not treat a successful merge as a completed deployment until these checks
have finished.
