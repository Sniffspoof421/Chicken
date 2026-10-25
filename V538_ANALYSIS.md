# V5.3.8 analysis — causal GREEN outcome + fullscreen reframe hardening

## Latest V5.3.7 run

The supplied run contains 7 resolved GREEN outcomes:
- 1 success
- 6 logged failures

All 6 logged failures were produced by the legacy crash-progress fallback rather
than a directly observed GREEN action. Their recorded motion spans roughly
1.87–2.07 lane steps, which violates the one-GREEN / one-jump ownership rule.

## Root causes

1. `GreenJumpOutcomeTracker.on_crash()` still contained a legacy fallback that
   could look back several seconds after GREEN, invent `action_start_ts=green_end`,
   and convert later crash geometry into a supervised GREEN failure.

2. Active/provisional outcome code checked regression before the multi-jump
   chain limit. A later reset after two-lane progress could therefore be called
   a GREEN failure before the one-jump guard was evaluated.

3. Fullscreen reframe detection compared only the immediately previous chicken
   X coordinate. At low FPS the normal game cut can be sampled across multiple
   frames (for example 1070 -> 700 -> 190), so the old detector could miss it.

4. A missed fullscreen cut could reach CrashDetector and be learned as a death
   before the reframe system got another chance to classify it.

## V5.3.8 corrections

- Removed crash-progress fallback GREEN failure generation.
- No observed action means no GREEN failure.
- Multi-jump progress is classified `chained_unvalidated`, never failure.
- One-jump ownership is checked before regression in active and provisional
  outcome states.
- `on_crash()` also checks the one-jump envelope before assigning failure.
- Fullscreen reframe uses a 1.6-second recent chicken-position peak.
- Added a secondary CrashDetector geometry reframe classifier that runs before
  crash/unsafe/GREEN-failure learning.
- Normal ~one-lane reset remains a crash; ~two-lane third-lane -> first-lane
  cut is progress.
- Attribution policy version raised to 538.
- On first load of pre-538 models, GREEN-only failure counters/source ETA floors
  and SafeWindow direct failure prototypes are cleared.
- Validated GREEN successes, long-term traffic learning, vehicle/type behavior,
  generic crash memory, speed/pattern/gap history are retained.
- Late timing tombstone reduced from 6.0 s to 1.8 s and remains diagnostic only.
- SafeWindow log renamed to `safe_window_v538_*.csv`.

## Regression checks

Passed:
- V5.3.8 causal outcome / one-jump / recent-peak / migration test
- V5.3.7 verified-gap fast path
- V5.3.6 expired-GREEN reliability policy
- V5.3.5 fullscreen reframe + outcome rebase
- V5.3.4 current-session speed authority
- V5.3.3 chicken-authoritative geometry
- V5.3.2 recent-session adaptation
- V5.3.1 progress-scroll Hardcore logic
- V5.3.0 target advancement
- V5.2.9 one-jump outcome geometry

## Run

Use `start_v538.bat`.

Keep the trained files:
- `data/models/online_state_v532.joblib`
- `data/models/safe_window_v532.joblib`

Do not delete them; V5.3.8 performs the one-time failure-memory cleanup itself.
