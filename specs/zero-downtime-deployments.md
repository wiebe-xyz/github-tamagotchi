# Zero-Downtime Deployments
**Status**: Implemented
**Created**: 2026-04-13

## Overview
The previous deploy strategy ran `kubectl apply` on the active deployment, causing 30–60 seconds of downtime while the init container ran migrations and the readiness probe passed. This spec describes the blue-green deployment strategy that eliminates that gap: a new image is deployed to the idle slot, brought fully healthy, and then traffic is flipped atomically.

## Goals / Non-Goals

**Goals**:
- Zero downtime on every deploy (no dropped requests during image rollout)
- Automatic rollback when the new deployment fails health checks
- Diagnostics (pod describe + container logs) emitted on failure so root cause is easy to find
- No external tooling beyond `kubectl` — works with the existing k3s + Traefik setup

**Non-Goals**:
- Database migration rollback — migrations are forward-only; this strategy does not address schema incompatibility between blue and green versions
- Canary / traffic splitting — traffic flips 100% atomically
- Multiple replicas per slot — each color runs at most one pod (sufficient for current traffic)

## How It Works

1. **Detect active color** — query the Service selector: `kubectl get service github-tamagotchi -o jsonpath='{.spec.selector.version}'`. Result is `blue` or `green`; the other is the inactive slot.

2. **Update idle deployment** — use `kubectl set image` to point both the app container (`github-tamagotchi`) and the init container (`migrate`) to the new image SHA. This updates the pod template without scaling anything.

3. **Scale idle deployment up** — `kubectl scale --replicas=1` on the inactive deployment. Kubernetes creates the pod, runs the init container (migrations), then starts the app container and waits for the readiness probe to pass.

4. **Wait for healthy** — `kubectl rollout status --timeout=900s`. The 900-second budget covers slow migrations. The rollout only succeeds once the readiness probe at `/api/v1/health/ready` returns 200.

5. **Atomic traffic switch** — `kubectl patch service` replaces `spec.selector.version` with the new color. Traefik picks up the endpoint change immediately; in-flight requests on the old pod complete normally thanks to the 30-second `terminationGracePeriodSeconds` and the 5-second `preStop` hook.

6. **Scale down old deployment** — `kubectl scale --replicas=0` on the previously active color. The old pod terminates gracefully.

## Failure Handling

If `kubectl rollout status` times out or the pod enters `CrashLoopBackOff`:

1. CI prints a diagnostic block: pod describe, init container logs, app container logs.
2. CI scales the inactive deployment back to 0 replicas.
3. CI exits with a non-zero code, failing the workflow — the PR/commit is flagged red.
4. The Service selector is **never patched**, so traffic continues flowing to the previously active color throughout. There is no user-visible impact.

## Deployment Procedure

### Manual (initial setup / emergency)
Use `task k8s:deploy` which:
1. Applies secrets.
2. Runs init jobs (database + MinIO provisioning).
3. Applies the manifest (`kubectl apply -f k8s/deployment.yaml`). **Warning:** `kubectl apply` respects the `replicas: 0` values in the file and will scale both deployments to 0, taking down any running pods. Step 4 immediately restores service.
4. Scales blue to 1 and waits for rollout status (assumes blue is the baseline active color after initial setup).

**Do not run `kubectl apply -f k8s/deployment.yaml` directly** while a deployment is live — use `task k8s:deploy` which handles the re-scale, or scope the apply to a specific resource (e.g. `kubectl apply -f k8s/deployment.yaml --dry-run=server` to preview).

### Automated (CI on every merge to main)
The `deploy` job in `.github/workflows/ci.yml`:
1. Detects the active color from the live Service.
2. Sets the new image on the inactive deployment.
3. Scales inactive up and waits for healthy.
4. Patches the Service selector (atomic flip).
5. Scales the old deployment down.

## Known Pitfalls

### TLS certificate configuration
The Ingress uses Traefik's built-in ACME via the annotation:
```yaml
traefik.ingress.kubernetes.io/router.tls.certresolver: letsencrypt
```
Traefik stores the cert in its own internal store — it does **not** write to a Kubernetes Secret. The `tls.secretName` field in the Ingress spec must be absent. If `secretName` is set, Traefik looks for a k8s Secret that doesn't exist and stops serving HTTPS, causing site-wide 503s. The correct TLS block is:
```yaml
tls:
  - hosts:
      - tamagotchi.nijmegen.wiebe.xyz
```
No `secretName`.

### `kubectl apply` resets replicas
The `replicas: 0` values in `k8s/deployment.yaml` are what the API server will enforce when `kubectl apply` runs. Applying the file while pods are live will immediately terminate them. Always use `task k8s:deploy` for manual deploys, which re-scales blue to 1 after applying.

### Migrations run on the new slot only
The init container runs `alembic upgrade head` before the app starts. Schema changes are applied to the database while the old slot is still serving traffic. Migrations must therefore be backwards-compatible with the currently-running code (i.e. additive-only, no column drops or renames until the old slot is gone).

## Files

| File | Role |
|------|------|
| `k8s/deployment.yaml` | Defines both blue and green Deployments (replicas: 0 — managed by deploy process), the Service, and the Ingress |
| `.github/workflows/ci.yml` | `deploy` job implements the blue-green swap logic |
| `Taskfile.yml` | `k8s:deploy` task for manual deploys; `k8s:logs` queries the active color dynamically |
