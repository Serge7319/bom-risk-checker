# Railway Build Failed Email Triage

Use this checklist when Railway sends a **Build failed** email while the
dashboard may also show an Active successful deployment.

This document does **not** assert a root cause for any past notification without
matching deployment IDs and timestamps.

## Concepts (do not conflate)

| Term | Meaning |
|------|---------|
| Build attempt | Compiling/packaging the service image or Railpack build |
| Deployment attempt | Promoting a build toward a running instance |
| Active successful deployment | The revision currently serving traffic |
| Failed superseded deployment | A failed or abandoned attempt replaced by a later one |
| Manual redeploy | Operator-triggered deploy |
| Configuration-triggered deploy | Variable/config change triggered a new build |
| Commit-triggered deploy | Git push / GitHub webhook triggered a build |
| Cancelled / skipped | Build never completed or was superseded mid-flight |

A failure email can refer to an older attempt even when a later Active deploy is healthy.

## Compare the email to Railway history

For **both** the email’d failure and the Active success, capture:

1. **Project** name (e.g. `incredible-radiance`)
2. **Service** name (e.g. `bom-risk-checker`)
3. **Environment** (e.g. `production`)
4. **Deployment ID** / Railway deployment URL
5. **Commit SHA**
6. **Trigger type** (push / manual / config / other)
7. **Created / build start / build end / deploy end** timestamps
8. **Build log tail** (last ~50 lines of the failed build)
9. Whether the failed deployment became **Inactive / Superseded / Crashed**
10. Whether another service or environment shares a similar name

## Is production affected?

Production is affected only if the **Active** deployment for the production
service is unhealthy or missing — not merely because a failure email arrived.

If Active is healthy on the expected commit SHA, treat the email as a
superseded/failed attempt until proven otherwise.

## Evidence to retain before redeploying

- Screenshots or exports of both deployment detail pages
- Exact deployment IDs and SHAs
- Build log excerpts (no secrets)
- Approximate email receipt time (timezone noted)

## Cadivor start command reference

Authoritative start path (`railway.toml` → `scripts/railway_start.sh`):

```bash
streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=$PORT
```

Builder: Railpack (`railway.toml`).

## Related performance logs

When `CADIVOR_STARTUP_TIMING` is enabled, Railway logs may include lines prefixed
`CADIVOR_PERF` and `[cadivor-startup]`. These measure latency; they do not explain
build email discrepancies.
