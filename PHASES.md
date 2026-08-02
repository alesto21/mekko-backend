# MinBil — Phase Roadmap & Status

This file is kept identical in both repositories that make up MinBil:
the Flutter client (`Mekko`) and the backend (`mekko-backend`). When a
phase starts, finishes, or changes scope, update both copies together —
don't let them drift.

Each repo also has its own `ARCHITECTURE.md` describing how that specific
codebase is structured today. This file is about *what phase the project
is in and why*, not implementation detail.

Last updated: 2026-08-02 (Phase 3A complete).

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
| 3 — Vertical slice extraction, feature by feature (client) | 🟡 In progress — 3A complete, see below |
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
- **`themeModeNotifier` has no effect on the app's actual rendered
  theme.** `MinBilApp.build()` hardcodes `Brightness.light` and never
  reads `themeModeNotifier` or sets `MaterialApp.themeMode`/`darkTheme`
  - so picking Light/Dark/System in the Appearance (`UtseendeScreen`)
  settings screen persists the choice via `SettingsService.setThemeMode`
  and updates `themeModeNotifier.value`, but nothing downstream ever
  acts on either, and the app always renders in light mode regardless
  of the selection. Discovered while tracing dependencies for the Phase
  3A plan (Settings/Profile/Feedback), not introduced by any phase's
  changes - pre-existing. Not fixed here; fixing it is a behavior
  change (wiring `MaterialApp.themeMode` to the notifier and building a
  dark `ThemeData`), which is explicitly out of scope for a mechanical
  relocation phase. Needs a deliberate decision on when to address it.

## Phase 3 — Vertical slice extraction, feature by feature — in progress
This is where the long-term feature-first direction actually takes
shape: one feature at a time (Settings/Feedback first as the
lowest-risk pilot, Garage/Parts/AI Mechanic last), each fully
extracted — model, service, repository, widgets — into its own
`lib/features/<name>/`, before moving to the next. State management
(if Provider/Riverpod is introduced) is a separate, later decision
within this phase, not bundled with the file moves themselves.

Order: **3A Settings/Profile/Feedback** (below, complete) → 3B
Onboarding → 3C Notifications → 3D Garage/Service Log → 3E Parts → 3F
AI Mechanic.

Two decisions this phase still needs to make, deliberately left open
since Phase 2: whether `Vehicle` (used by every feature) stays in a
shared location permanently or gets a different resolution, and
whether the Parts-feature-coupled classes flagged in Phase 2
(`PartCategory`/`PartShop`/`TecDocPart`/`EngineMatch`/
`VehicleResolution`) move into `lib/features/parts/` as part of that
feature's slice. Neither was touched by 3A.

### Phase 3A — Settings/Profile/Feedback vertical slice ✅ Complete

**What changed.** 10 commits on `phase-3a-settings-feature` (9 planned
extraction commits + 1 approved mid-phase prep commit), each verified
against the Phase 2 analyzer baseline and the full test suite before
moving to the next:

1. `_SettingsSection`/`_SettingsTile`/`_SettingsToggleTile`/`_ThemeOptionTile`
   (renamed public, forced by cross-file sharing) →
   `lib/features/settings/widgets/settings_tiles.dart`
2. `FeedbackService` → `lib/features/settings/services/feedback_service.dart`
3. `PersonvernScreen` + `_PrivacyParagraph` →
   `lib/features/settings/screens/personvern_screen.dart`
4. `ProfilScreen` + `_ProfileField` →
   `lib/features/settings/screens/profil_screen.dart`
5. `UtseendeScreen` →
   `lib/features/settings/screens/utseende_screen.dart` — moved
   as-is; **still unreachable**, see below
6. `SprakScreen` → `lib/features/settings/screens/sprak_screen.dart`
7. `VarslingerScreen` → `lib/features/settings/screens/varslinger_screen.dart`
8. **Prep commit (not in the original 9-item plan, approved
   separately mid-phase):** `_FormLabel`/`_ErrorBox` promoted from
   private to public `FormLabel`/`ErrorBox` in
   `lib/shared/widgets/form_helpers.dart`. Forced because
   `FeedbackScreen` (moving next) shared these two trivial widgets
   with code that wasn't moving yet (another screen, and the
   still-embedded service-entry form) — Dart's file-scoped privacy
   meant `FeedbackScreen` couldn't take a private copy without either
   duplicating or promoting them. Promoted, matching the Phase 2
   shared-layer pattern rather than duplicating.
9. `FeedbackScreen` → `lib/features/settings/screens/feedback_screen.dart`
10. `InnstillingerScreen`/`_InnstillingerScreenState`/`_ProBanner`/
    `_ProActiveBanner`/`_ProfileHeader`/`_themeModeLabel` (dead, moved
    as-is) → `lib/features/settings/screens/innstillinger_screen.dart`
    — the hub screen; the point where `main.dart` finally lost every
    settings-specific import

Every move was mechanical — no logic, copy, layout, styling,
persistence keys, or navigation targets changed. `main.dart`: 8,896 →
7,177 lines (**-1,719, ~19%**). Test suite: 26 → **72 tests**
(20 new files across the two commits above plus the 7 extraction
commits' own test files).

**Why it was changed.** Settings/Profile/Feedback was chosen as the
pilot vertical slice because it's the lowest-risk corner of the app:
no real-time data, no payment flow, mostly `SharedPreferences` reads
and simple navigation. Proving the feature-first pattern here first —
including the messy parts, like the `FormLabel`/`ErrorBox` sharing
conflict — de-risks the harder slices (3D Garage, 3E Parts, 3F AI
Mechanic) that come later.

**Temporary two-way imports (accepted, not a defect).** Every
extracted settings screen still imports symbols back from `main.dart`
via `show` clauses, because the services and global notifiers those
screens depend on (`SettingsService`, `SubscriptionService`,
`NotificationService`, `Garage`, `ServiceLog`, `isProNotifier`,
`tireRegionNotifier`, `PaywallScreen`) haven't been extracted
themselves — that's later slices' job (`NotificationService` is 3C,
`Garage`/`ServiceLog` are 3D). This two-way dependency between
`main.dart` and `lib/features/settings/` is a deliberate, temporary
consequence of extracting one feature while its shared dependencies
still live in `main.dart` — Dart permits it without error, and it's
expected to shrink and eventually disappear as those services move in
their own future slices, not something to "fix" now.

**Findings from Phase 3A (pre-existing, not introduced by it):**
- **`UtseendeScreen` is unreachable.** No navigation anywhere in the
  app (production or otherwise) constructs it — confirmed by grepping
  every commit's diff, including this one, for `UtseendeScreen(`.
  Moved verbatim in Commit 5 without adding a navigation path, per
  explicit instruction not to make it reachable as a side effect of
  relocation. Still true after Phase 3A completes.
- **`themeModeNotifier` still has no effect on the app's rendered
  theme** — see the full description under Phase 2's remaining debt
  above. Unchanged by Phase 3A; `InnstillingerScreen` and
  `UtseendeScreen` both still just persist the choice and bump the
  notifier, and nothing downstream reads it.
- **`SubscriptionService.isPro()` never resolves inside a
  `testWidgets` test when `Purchases.configure()` hasn't been
  called** — discovered writing `innstillinger_screen_test.dart`.
  Outside a widget test it resolves in ~2ms (caught
  `MissingPluginException`, verified with a standalone probe); inside
  one, it hangs indefinitely (confirmed with real multi-second
  wall-clock waits, not just a `pumpAndSettle` timeout). Because
  `_loadSettings()` calls `isPro()` last and is fire-and-forget from
  `initState()`, this doesn't hang the test itself — it just means
  `InnstillingerScreen`'s `_loadSettings()`-derived state (profile
  name/email, notifications flag, tire region, isPro) can only be
  verified against pre-load default values in any widget test that
  mounts it, never the `SharedPreferences`-loaded ones. No DI seam
  exists to fix this without changing production code; out of scope
  for a mechanical relocation phase, left as a finding for whoever
  next needs to unit-test Pro-gated UI.

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
  8 commits on `phase-2-shared-layer`, merged to `main` and tagged
  `phase-2-complete`.
- 2026-08-02 — Phase 3A (Settings/Profile/Feedback) complete (client
  only). 11 commits on `phase-3a-settings-feature`, merged to `main`
  and tagged `phase-3a-complete`.
  `main.dart`: 8,896 → 7,177 lines. Test suite: 26 → 72 tests. Phase
  3B (Onboarding) not started.
