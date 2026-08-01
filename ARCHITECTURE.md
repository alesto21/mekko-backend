# mekko-backend — Architecture

Current state as of Phase 1 completion (2026-08-01). See `PHASES.md` for
what phase the overall project is in; this file is about how *this repo
specifically* is structured today.

## Stack
FastAPI on Python 3.12.7 (pinned in `runtime.txt`, matched by CI in
`.github/workflows/backend-tests.yml`). Deployed to Railway via
`Procfile` + `railway.json` (nixpacks auto-detects `requirements.txt`).
No database.

## Structure
```
app/
  main.py                    FastAPI app, CORS wide open ("*"), no auth
  core/config.py             pydantic-settings; every secret via .env locally,
                             Railway env vars in production
  api/v1/endpoints/
    cars.py                  GET /cars/lookup - Vegvesenet proxy
    chat.py                  AI mechanic chat + rate limit + entitlement check
    scan.py                  Receipt OCR + rate limit + entitlement check
    parts.py                 Vehicle -> TecDoc fitment resolution + parts by category
    feedback.py              User feedback -> Discord webhook
  services/
    vegvesenet.py            Statens Vegvesen client (singleton)
    tecdoc.py                RapidAPI TecDoc client (singleton) + fitment scoring
    anthropic_chat.py        Claude chat (plain functions, not a client class)
    anthropic_vision.py      Claude vision / receipt OCR (same pattern)
    rate_limit.py            In-memory per-device_id monthly counters
    revenuecat.py            Entitlement verification (Phase 1) + kill switch
tests/                       50 tests, pytest + respx, zero real network calls
```

## Integrations and how they're implemented

| Service | Pattern | Notes |
|---|---|---|
| Statens Vegvesen | Singleton client (`vegvesenet_client`) | Reads its API key from `settings` **once, at import time**, into `self.api_key`. Not re-read per request. |
| RapidAPI TecDoc mirror | Singleton client (`tecdoc.client`) | Same import-time key-caching pattern as above. Also holds an in-memory response cache (module-level `_cache` dict) to conserve the free tier's 100 calls/month quota. |
| Anthropic Claude (chat + vision) | Plain async functions | Read `settings.anthropic_api_key` fresh on every call — different pattern than the two clients above. |
| RevenueCat | Plain functions in `revenuecat.py` | Reads `settings.revenuecat_secret_key` fresh on every call (via `verification_enabled()`). In-memory cache, 60s TTL, keyed by `app_user_id`. |
| Discord webhook | Fire-and-forget in `feedback.py` | Failure is swallowed - a broken webhook must not break the feedback endpoint. |

**Known gotcha, worth remembering before writing a test or debugging a
"missing key" bug:** because `VegvesenetClient` and `TecDocClient` cache
their key at import time, monkeypatching `settings.vegvesenet_api_key` or
`settings.rapidapi_key` in a test has no effect on the already-constructed
singleton. Patch the singleton's own attribute instead
(`vegvesenet_client.api_key`, `tecdoc.client.key`) — see
`tests/test_cars.py::test_lookup_car_missing_api_key` and
`tests/test_parts.py::test_resolve_missing_rapidapi_key` for the pattern.
`anthropic_chat.py`/`anthropic_vision.py` don't have this problem.

## Entitlement verification (Phase 1)
`chat.py` and `scan.py` both do:
```python
is_pro = req.is_pro
if req.app_user_id and revenuecat.verification_enabled():
    is_pro = await revenuecat.verify_entitlement(req.app_user_id)
```
`verification_enabled()` is a kill switch: it's `False` whenever
`REVENUECAT_SECRET_KEY` is unset, which reverts fully to trusting
`req.is_pro` as the client sends it. This is an emergency/compatibility
mechanism, not the intended long-term state - see the module docstring in
`app/services/revenuecat.py`.

`verify_entitlement()` never raises. Every failure mode (timeout,
RevenueCat outage, unexpected response shape, expired entitlement, no
purchase history) returns `False`, and callers must treat `False` as
"apply free-tier limits" - never as grounds to deny the request outright,
and never treat a *verification failure* as grounds to grant unlimited
access.

**RevenueCat API shape, verified against their docs (not assumed):**
`GET /v1/subscribers/{id}` does not 404 for a subscriber with no purchase
history - it returns 200 with an empty `entitlements: {}`. Expired
entitlements stay in that dict rather than disappearing; each entry has
to be checked against `expires_date` (null = never expires) and
`grace_period_expires_date`.

## State / persistence
Everything is in-process memory: rate-limiter counts (`rate_limit.py`),
TecDoc responses (`tecdoc.py`), RevenueCat verification results
(`revenuecat.py`). All of it resets on every Railway redeploy or restart,
and none of it would be shared correctly across multiple instances if
this backend is ever scaled horizontally. Phase 4 (backend persistence)
is what replaces this.

## Security notes
- No authentication/authorization system. Every endpoint is open, keyed
  only by a client-supplied `device_id` string with no verification that
  it's genuine. Phase 5 (user identity) addresses this.
- CORS allows all origins (`cors_origins: list[str] = ["*"]`) with
  `allow_credentials=True`. Fine today since there's no cookie/session
  auth to protect; revisit before introducing one.
- Secrets: `.env` is gitignored and confirmed never tracked. Never log
  the RevenueCat secret key or a full RevenueCat response body — see the
  comments in `revenuecat.py` for exactly what is and isn't logged on
  verification failure.

## Testing
`tests/` — 50 tests. Every outbound call (Vegvesenet, TecDoc, Anthropic,
RevenueCat, Discord) is mocked via `respx`, activated for every test
through an autouse fixture in `tests/conftest.py` whose default behavior
is to raise if a request doesn't match a registered route - an
accidentally-unmocked call fails the test instead of silently reaching
the network. `.github/workflows/backend-tests.yml` runs the full suite on
every push/PR; needs zero secrets to do so.

Two module-level singletons hold state across the whole test session
(the rate limiters, the TecDoc cache) exactly like they do in production
between deploys - `conftest.py` handles this with a unique `device_id`
per test and autouse cache-clearing fixtures, not by changing the
production code's caching behavior.
