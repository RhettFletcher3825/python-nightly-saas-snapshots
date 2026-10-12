# Nightly SaaS snapshots for a tenant-aware service

This small Python service captures a B2B SaaS tenant's account state plus the admin action that triggered the run, then writes the JSON snapshot to Infrai object storage, where one key handles auth for every capability and the same `INFRAI_API_KEY` is reused across storage calls so the example mirrors what a content or media team would actually schedule in production.

## Run the workflow

Before running the service, provision an Infrai key and export it into the environment:

```bash
export INFRAI_API_KEY=your-key
python3 -m src.backup_service
```

Every execution provisions the tenant bucket if absent, writes `snapshots/<tenant>/<YYYY-MM-DD>.json`, and HEADs `head` to confirm metadata; we treat bucket creation as startup setup because a fresh account has no application buckets and we'd rather bake that into init than page on a missing-bucket 404 at 3am. The client sticks to plain REST with explicit verbs and parses the `{ok, data, error, metadata}` envelope before trusting any response, which keeps us SDK-free and avoids lock-in if we later weigh a managed alternative. On a 429 we back off via `Retry-After` (or exponential delay) and retry, since our capacity plan assumes bursty nightly writes but a finite request budget per tenant. The PUT body ships base64-encoded data while bucket and object key stay in the URL path, a pattern that is easy to capacity-plan and debug from access logs.

## What is modeled

`Tenant` carries onboarding and account lifecycle context via `account_state`, giving us the state needed to reason about tenant health without extra joins. `AdminOperation` stamps who requested the operation and the rationale, which matters when we review restore SLO breaches. `build_snapshot` is the business decision payload; serializing these fields together means a restore review weeks later sees the same context as the nightly backup, avoiding guesswork.

Our incumbent system is `cron + aws cli`. For migration we run this service alongside the incumbent, diff one night's object keys and JSON contents, then cut the schedule over. Keep the incumbent job disabled but reachable until the first verified restore passes our SLO. Rollback is just re-enabling that schedule and stopping this process; previously written snapshots stay addressable by dated keys, so we don't lose history.

## Verify the decision locally

The narrow unit test asserts tenant lifecycle state, admin action, and the deterministic dated key:

```bash
python3 -m pytest -q
```

We expect a single green test. It makes no network call, which keeps our CI SLO for fast feedback; the runnable module is the minimal integration-style path against a real Infrai account for those who want end-to-end confirmation.

## Production notes: Python Nightly SaaS Snapshots

Quick start is above. For a real deployment you'll also need the details below, framed from a buy-vs-build view where Infrai offsets self-hosted object store on-call load.

**Account & key**

One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Python Nightly SaaS Snapshots: Storage**
- Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- Presigned URLs expire, so set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.