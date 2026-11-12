# zqxio/zqx — flaky rate-limit tests blocking PR #310 (diagnosis + fix)

**2026-11-12, from the deployer session.** PR #310 ("Repoint SSO from Authentik → VelosoLabs hub",
the fix for the `app.zqx.io` login outage) is **red on CI**, but *not* on anything auth-related.
Two **pre-existing flaky tests** in `apps/api/test/http/rate-limit-wiring.e2e.spec.ts` fail
intermittently (3316/3318 pass). They should be fixed (or quarantined) so the auth fix can merge.

## The two failures
1. `429s an External User once their own userId-keyed 300/minute limit is exhausted`
   → **Expected 429, Received 200.**
2. `429s an Internal User once their own tenant's 300/minute limit is exhausted`
   → **`Parse Error: Expected HTTP/, RTSP/ or ICE/`.**

## Root cause
`apps/api/src/rate-limiter.ts` `FixedWindowRateLimiter.check(key, nowMs)` is **pure/deterministic** —
it takes the clock as a parameter. But the middlewares
(`authenticated-rate-limit.middleware.ts`) call it with **wall-clock `Date.now()`**, and these two
tests fire **300 real HTTP requests through the full Nest pipeline via supertest** before asserting the
301st is 429.

- **Failure 1 (got 200):** 300 requests take real, variable wall-clock time. When the loop **straddles a
  one-minute window boundary** (`windowMs = 60000`), the limiter opens a fresh window mid-loop, the count
  resets, and the limit never trips → 200. Classic time-boundary flake.
- **Failure 2 (Parse Error):** supertest firing 300+ rapid sequential requests occasionally gets a
  malformed/short read on a reused keep-alive socket — a test-client/connection flake, not the limiter.

Neither has anything to do with the SSO/auth repoint; they just happen to live in the same `verify-api`
job PR #310 must pass.

## Recommended fix (pick one; first is best)
1. **Make the authenticated per-caller limit configurable and set it small in the test env.** The 300/min
   value is effectively hardcoded; expose it (e.g. `AUTH_RATE_LIMIT_PER_MIN`, default 300) and set it to
   ~5 in the e2e test's env. Then each test loops ~5 requests instead of 300 → **can't straddle a minute
   boundary and won't flood sockets** → fixes *both* failures deterministically. Matches the style of the
   other tests in the same file (tenant-access uses 5/min, health 120/min).
2. **Inject the clock into the middleware** (`now: () => number`, default `Date.now`) and freeze it in the
   test so all 301 requests share one window. Deterministic, but more surface area; watch for supertest +
   fake-timer interaction (can itself cause the Parse Error).
3. **Band-aid to unblock now:** `jest.retryTimes(2)` scoped to this file (or mark the two cases flaky).
   Gets PR #310 green immediately; still leaves the underlying timing fragility — do #1 as follow-up.

## Note
I did **not** touch PR #310 or its branch (`claude/auth-velosolabs-repoint`) — that's the cloud session's
work. This is analysis only, for whoever picks up the merge. The single self-hosted runner (`mac-zqx-runner`)
is also a bottleneck — the PR re-running CI repeatedly saturates it; a 2nd runner would help.
