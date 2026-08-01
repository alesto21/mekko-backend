# MinBil — Phase Roadmap & Status

This file is kept identical in both repositories that make up MinBil:
the Flutter client (`Mekko`) and the backend (`mekko-backend`). When a
phase starts, finishes, or changes scope, update both copies together —
don't let them drift.

Each repo also has its own `ARCHITECTURE.md` describing how that specific
codebase is structured today. This file is about *what phase the project
is in and why*, not implementation detail.

Last updated: 2026-08-01 (Phase 2 complete).

## Architecture direction (read this before touching Phase 2's output)

The shared layer created in Phase 2 (`lib/models/`, `lib/theme/`,
`lib/config/`) is **temporary, not the end state**. The long-term
direction is feature-first architecture: vertical slices where each
feature owns its own models, services, repositories, and widgets, per
Phase 3 below. Phase 2 exists because pulling out the truly
ownerless, cross-feature pieces (things every feature already touches -
`Vehicle`, theme tokens, config) had to happen before any per-feature
work could start safely, and it was faster and lower-risk to give them
one shared home first rather than deciding their final per-feature
destination up front. When Phase 3 vertical slices land, expect
`lib/models/` to shrink or disappear as truly feature-owned data moves
into `lib/features/<name>/`, and expect `Vehicle` specifically to need
a deliberate decision then (it's used by every feature, so it may stay
shared rather than move into any one feature - that decision is Phase
3's to make, not pre-empted here).

## Status at a glance

| Phase | Status |
|---|---|
| 0 — Audit and documentation | ✅ Complete |
| 1 — Foundation (safety net + is_pro fix) | ✅ Complete — tag `phase-1-complete` |
| 2 — Domain model & shared-layer extraction (client) | ✅ Complete — temporary shared layer, see above |
| 3 — Vertical slice extraction, feature by feature (client) | Not started |
| 4 — Backend persistence | Not started |
| 5 — User identity (anonymous-first, Apple/Google sign-in later) | Not started |
| 6 — Vehicle Knowledge Engine v1 | Not started |
| 7 — Cloud sync | Not started |
| 8 — Better AI context | Not started |
| 9 — Advanced parts compatibility | Not started |
| 10 — Affiliate retailers | Not started |
| 11 — Price comparison | Not started |
| 12 — Mechanic booking | Not started |

## Phase 1 — Foundation ✅ Complete

### What changed
Four work items, each reviewed and approved separately, committed in
small logical commits on `phase-1-foundation` in both repos, merged to
`main` and tagged `phase-1-complete`:

- **A — Fixed the broken Flutter test.** `test/widget_test.dart`
  referenced a `MyApp` class that doesn't exist (the real root widget is
  `MinBilApp`) — `flutter test` couldn't even compile. Replaced with a
  real fresh-install onboarding smoke test.
- **B — Backend test scaffolding.** Added `pytest` + `respx`, and a
  baseline test for every existing endpoint's current behavior (health,
  cars, chat, scan, parts, feedback). Zero production code touched.
  All outbound calls (Vegvesenet, TecDoc, Anthropic, Discord) mocked —
  no real network access from the test suite, ever.
- **C — Closed the `is_pro` trust gap.** The backend previously trusted
  a client-supplied `is_pro: true` with no verification — a raw HTTP
  request could get unlimited AI-mechanic and receipt-scan usage with no
  purchase behind it. Added `app/services/revenuecat.py`, which checks
  the claim against RevenueCat's real subscriber record when the request
  includes `app_user_id` and `REVENUECAT_SECRET_KEY` is configured.
  Backward compatible by construction: no `app_user_id` (old app
  versions) or an unset secret key (kill switch) both fall back to the
  exact legacy behavior. A RevenueCat outage or any verification failure
  falls back to free-tier limits — never unlimited, never a hard failure.
- **D — Client sends RevenueCat's real identifier, Android permission
  fix, CI for both repos.** `SubscriptionService.appUserId()` added to
  the Flutter client (API confirmed against the installed
  `purchases_flutter` 9.16.0 source before writing it, not assumed) and
  threaded into the two request bodies that needed it. Added the missing
  `INTERNET` permission to the release Android manifest. Added GitHub
  Actions CI to both repos.

### Why it was changed
Before touching any architecture, the project needed two things it
didn't have: a way to know when something breaks (there was no working
test in either repo), and a fix for the one issue with a direct, ongoing
revenue impact (the unverified `is_pro` flag). Restructuring a 9,500-line
file with zero regression detection would have been reckless — this
phase existed to make that safe to attempt later, not to add features.

### Risks removed
- The `is_pro` bypass is closed for any client that sends `app_user_id`,
  with a documented, tested kill switch if the fix itself ever needs to
  be backed out without a deploy.
- Both repos now have a real, passing, non-trivial test suite (50 backend
  tests, 1 Flutter test) wired into CI on every push/PR — regressions in
  what Phase 1 touched will be caught automatically going forward.
- A release Android build silently missing the `INTERNET` permission is
  fixed (discovered during the audit, closed here).

### Remaining technical debt (explicitly not addressed in Phase 1)
Left alone deliberately — these are Phase 2+ territory, not oversights:
- `lib/main.dart` is still one 9,500+ line file. No `lib/features/`,
  `lib/core/`, `lib/repositories/`, etc. yet.
- No database anywhere. User data lives in `SharedPreferences` on
  device; backend rate-limit counts and caches are in-process memory
  that resets on every Railway redeploy.
- No user identity/accounts system. A "user" is still just a
  self-generated `device_id` string.
- 20 pre-existing Flutter analyzer info/warning issues (unused private
  widgets, one deprecated RevenueCat API call, naming nits) — not fixed;
  CI is configured to not block on them, but they're visible in every
  run's log.
- **Android currently cannot produce a debug build at all**
  (`flutter_local_notifications` requires Java 8 core library
  desugaring, which isn't configured) — discovered while verifying the
  `INTERNET` permission fix, confirmed pre-existing and unrelated, not
  fixed here.
- Parts "buy" links are still just Google Shopping / Autodoc search
  URLs, not real offers.
- Generic, non-vehicle-specific service intervals are still hardcoded in
  the parts category UI.

## Phase 2 — Domain model & shared-layer extraction (client) ✅ Complete

### What changed
Eight small, individually-approved commits on `phase-2-shared-layer`,
each verified against a fixed Phase 1 analyzer baseline and the full
test suite before moving to the next:

1. `_ColorTokens`/`_lightTokens`/`_darkTokens`/`MinBilColors` →
   `lib/theme/minbil_colors.dart`
2. `TireRegion`/`TireRegionLabel`/`TireSeasonStatus` →
   `lib/models/tire_season.dart`
3. `RateLimitException` → `lib/models/rate_limit_exception.dart`
4. `ChatMessage` → `lib/models/chat_message.dart`
5. `ServiceType`/`ServiceTypeLabel`/`ServiceEntry` →
   `lib/models/service_entry.dart`
6. `ScannedReceipt` → `lib/models/scanned_receipt.dart`
7. `Vehicle`/`EuStatus`/`titleCase` (renamed from `_titleCase`) →
   `lib/models/vehicle.dart` - the highest-risk single move, ~366 lines,
   the app's most pervasively-used class
8. `kProEntitlementId`/`revenueCatIosApiKey` (renamed from
   `_revenueCatIosKey`)/`backendBaseUrl` (replacing five duplicated
   `_backendBase` declarations) → `lib/config/app_config.dart`

Every move was mechanical - no logic, values, JSON keys, enum order,
color mappings, or thresholds changed. The only renames were the three
forced by Dart's file-scoped privacy (`_titleCase`, `_revenueCatIosKey`,
and consolidating `_backendBase`); every rename is documented in its
commit message with the exact call sites it touched.

**8 new files, 52 new tests** (53 in the suite total, up from 1).
`main.dart`: 9,532 → 8,896 lines (-636, ~6.7%).

### Why it was changed
`main.dart` had no internal boundaries at all - every model, every
service, every screen in one 9,500-line file. Phase 2 pulled out the
pieces with no feature owner (used across garage, chat, scan, and
settings alike) so that Phase 3's feature-by-feature work has something
stable to import from, without deciding yet how those shared pieces
should ultimately be organized (see "Architecture direction" above).

### Flagged, not moved
Explicitly identified during planning as feature-coupled despite
looking like shared models, and left in `main.dart` for Phase 3's Parts
vertical slice to take: `PartCategory`, `PartShop`, `TecDocPart`,
`EngineMatch`, `VehicleResolution` - all used exclusively within the
Parts/Bildeler feature, nowhere else.

### Remaining technical debt (as of Phase 2)
Everything listed under Phase 1 above still applies. Additions specific
to Phase 2:
- `lib/models/service_entry.dart` and `lib/models/vehicle.dart` both
  import `flutter/material.dart` (`IconData`/`Color`) - an inherited
  UI/domain mixing, not introduced by this phase and not fixed by it.
  Worth a decision whether Phase 3 addresses this or accepts it
  permanently.
- `main.dart` is still ~8,900 lines. The line-count reduction from
  Phase 2 was real but modest by design - the bulk of the file is
  screens/widgets, which is Phase 3's job.
- State management (`ValueNotifier`s) untouched, as planned -
  introducing Provider/Riverpod is a separate future decision, not
  bundled into this relocation.

## Phase 3 — Vertical slice extraction, feature by feature — planned
This is where the long-term feature-first direction actually takes
shape: one feature at a time (Settings/Feedback first as the
lowest-risk pilot, Garage/Parts/AI Mechanic last), each fully
extracted — model, service, repository, widgets — into its own
`lib/features/<name>/`, before moving to the next. State management
(if Provider/Riverpod is introduced) is a separate, later decision
within this phase, not bundled with the file moves themselves.

Two decisions this phase needs to make that Phase 2 deliberately left
open: whether `Vehicle` (used by every feature) stays in a shared
location permanently or gets a different resolution, and whether the
Parts-feature-coupled classes flagged in Phase 2
(`PartCategory`/`PartShop`/`TecDocPart`/`EngineMatch`/
`VehicleResolution`) move into `lib/features/parts/` as part of that
feature's slice.

## Phase 4 — Backend persistence — planned
Postgres on Railway. `VehicleConfiguration` schema populated from the
existing Vegvesen/TecDoc resolution pipeline (not rewritten — given
somewhere durable to write its results). Prerequisite for Phases 6 and 7.

## Phase 5 — User identity — planned
Anonymous-first: users can use MinBil without creating an account.
Cloud sync, cross-device access, and premium features add Sign in with
Apple and Sign in with Google later. RevenueCat's own anonymous
`appUserID` (already wired in Phase 1) is the anchor — RevenueCat
supports aliasing an anonymous ID to a real identity via `logIn()`
without losing purchase history, so this doesn't require rework of
Phase 1's entitlement verification.

## Phase 6 — Vehicle Knowledge Engine v1 — planned
Formalize `VehicleConfiguration`, `DataSource`, `ConfidenceLevel`,
`VehiclePartCompatibility` on top of Phase 4's database, replacing
today's transient `confident: bool` with an auditable, source-attributed
record. Builds on the existing TecDoc scoring logic in
`app/services/tecdoc.py` — that matching approach is sound, it just has
nowhere durable to live yet.

## Phase 7 — Cloud sync — planned
Garage and service-log data sync via Phase 5 identity + Phase 4 database.
Local `SharedPreferences` data becomes a cache/offline-fallback, not the
source of truth. Requires an explicit migrate-on-first-sync step that
merges rather than overwrites existing local data.

## Phase 8 — Better AI context — planned
## Phase 9 — Advanced parts compatibility — planned
## Phase 10 — Affiliate retailers — planned
## Phase 11 — Price comparison — planned
## Phase 12 — Mechanic booking — planned
Sequenced behind the Vehicle Knowledge Engine deliberately — building
"advanced compatibility" or real retailer offers against an empty
knowledge engine is exactly where fabricated-looking data creeps in.

## Change log
- 2026-08-01 — Phase 1 complete. Merged to `main` in both repos, tagged
  `phase-1-complete`.
- 2026-08-01 — Phase 2 complete (client only, no backend changes).
  8 commits on `phase-2-shared-layer`, pending merge/tag.
