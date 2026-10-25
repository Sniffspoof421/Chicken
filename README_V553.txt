Chicken Road 2 AI Live V5.5.3
SESSION GAP PRIOR BOOTSTRAP + POST-JUMP REARM RELEASE

RUN
  start_v553.bat

WHAT THE V5.5.2 RUN ACTUALLY SHOWED

Duration:
  ~9.4 minutes

GREEN:
  2 GREEN signals
  1 acted GREEN
  1 confirmed GREEN success
  0 confirmed GREEN failures

So the supplied V5.5.2 run is primarily a GREEN-starvation / state-recovery
failure, not a newly proven unsafe-GREEN failure.

DOMINANT BLOCKERS
  LIVE GAP UNVERIFIED  ~2206 SafeWindow rows
  FORECAST ETA         ~1032
  VISION/VIEWPORT       ~322
  TRACK REWARM          ~238
  CLEAR LEASE           ~140

Processing was healthy at roughly 6.8 FPS average. CPU/FPS is not the main cause.

ROOT CAUSE — GAP HISTORY KEEPS BEING ERASED

The run contains:
  lane-phase realigns:        15
  fullscreen/progress cuts:   11
  target switches:            57

A legitimate geometry reanchor clears the local motion-gap history because the
old X corridor cannot directly certify the new lane.

That is individually correct.

But during active play the combination becomes:
  build 5-9 gap samples
  -> jump / phase correction / progress cut
  -> clear local gap history
  -> rebuild
  -> clear again

Observed motion-gap support:
  median = 8

Mature support required:
  EASY     8
  NORMAL   9
  HARD    10
  EXTREME 12

Most of this run was HARD/NORMAL/EXTREME, so the predictor was repeatedly just
below maturity.

dynamic_gap_ready was true on only about 1.2% of state rows.

SECOND BOOTSTRAP DEADLOCK

While local support is <=9, the dynamic horizon is normally capped by the
clear-zone geometry ETA.

In this run that geometry repeatedly sat around ~1.4 s.

So a newly rebuilt lane can have several strong ~2 s empirical gaps, yet before
full maturity its usable horizon is clamped back near ~1.4 s. That leaves little
or no action lease and prevents verification.

V5.5.3 FIX 1 — TWO-LEVEL GAP MEMORY

LOCAL GAP HISTORY
  Still resets on geometry reanchor.
  It remains authoritative for the currently watched lane.

SESSION GAP PRIOR
  New bounded 180 s current-session lower-tail prior.
  Survives geometry reanchor.
  Cannot create a GREEN by itself.

Bootstrap requires BOTH:
  enough NEW local completed gaps
  AND enough current-session prior gaps

Bootstrap local minimum:
  EASY      5
  NORMAL    5
  HARD      6
  EXTREME   7

Mature support requirements remain unchanged:
  8 / 9 / 10 / 12

The new lane must also have a sufficiently strong local P25:
  EASY     >=1.75 s
  NORMAL   >=1.85 s
  HARD     >=1.95 s
  EXTREME  >=2.05 s

The conservative bootstrap lower bound is:
  min(current-lane recent lower-tail, session-prior lower-tail)

Therefore historical/session traffic can NEVER make the new lane look better
than its own recent completed gaps.

A minimum 0.30 s physical headroom above dynamic required ETA is required before
the CZN bootstrap cap can be bypassed.

Bootstrap confidence is stricter than normal mature confidence.

V5.5.3 FIX 2 — RECHECK / POST-JUMP STUCK RELEASE

The supplied V5.5.2 state contains two RECHECK episodes around:
  ~9.48 s
  ~9.33 s

rearm_needed remained active while normal game progress changed chicken screen X.

The old rearm release depends heavily on absolute chicken X stability.
That coordinate is not reliable during normal progress/viewport movement.

V5.5.3 adds geometry-based rearm release.

RECHECK can clear after a short ~0.28 s dwell when all of these independently
prove a landed state:
  chicken fresh
  chicken anchor stable
  target geometry valid
  no tracking rewarm
  next target about 0.68-1.35 lane ahead
  stable target ownership / viewport generation

The old absolute-X rearm logic remains as a fallback.

V5.5.3 FIX 3 — LANDING WAIT WATCHDOG

WAIT_CHICKEN_LAND also gets a bounded watchdog.

If it persists >=1.35 s while:
  chicken is fresh
  anchor is stable
  viewport is stable
  next lane geometry can be calculated

the target is rebuilt from the CURRENT chicken position instead of waiting for
manual screen movement.

PRESERVED FROM V5.5.2 / EARLIER

- V5.5.2 degraded-FPS headroom
- V5.5.2 positive progress-scroll GREEN handoff
- V5.5.1 0.55 s recent-direct-threat tail
- V5.5.0 provisional landing survival
- physical timing-source failure feedback
- V5.4.9 / V5.4.7 GREEN profiles
- EASY / NORMAL / HARD / EXTREME switching
- centered post-pass GO-NOW timing
- click-vs-CV reaction split
- current-session speed authority
- one GREEN = one jump
- no crash->fake-action fallback
- fullscreen third-lane reframe
- unique low-weight manual success learning
- strong physical override of stale ML

IMPORTANT
This build does NOT globally lower:
  ETA
  mode support requirements
  GREEN probability
  threat-tail dwell
  action lease

The new prior is only a reanchor bootstrap.

NEW TELEMETRY
  dynamic_gap_session_prior_support
  dynamic_gap_session_prior_lower_bound
  dynamic_gap_bootstrap_candidate
  dynamic_gap_bootstrap_active
  dynamic_gap_bootstrap_lower_bound
  dynamic_gap_bootstrap_min_local_support
  landing_wait_age
  landing_wait_watchdog_recoveries
  landing_wait_watchdog_recovered
  green_rearm_geometry_releases

SAFE WINDOW LOG
  safe_window_v553_*.csv

MODELS
Keep the existing:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do not reset them.
