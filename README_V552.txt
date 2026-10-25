Chicken Road 2 AI Live V5.5.2
DEGRADED-FPS HEADROOM + HIDDEN PROGRESS HANDOFF

Run:
  start_v552.bat

BASE
V5.5.2 is built directly from V5.5.1.

UNCHANGED:
- V5.5.1 direct threat-tail maturity
- V5.5.0 causal landing survival/source feedback
- V5.4.9/V5.4.7 GREEN profiles and difficulty modes
- centered post-pass GO-NOW timing
- click-vs-CV timing split
- causal one-GREEN/one-jump ownership
- fullscreen third-lane reframe
- current-session speed guard
- physical verified-gap ML override

FIX 1 — DEGRADED-FPS GREEN NEEDS REAL HEADROOM

At processing <2.8 FPS:
  required frame reserve =
      1/FPS + 0.04 + 0.08 seconds

At >=2.8 FPS:
  V5.5.1 behavior is unchanged.

The latest suspicious GREEN:
  FPS 2.3415
  action lease 0.4785 s
  old requirement 0.4671 s
  real surplus only ~0.011 s

V5.5.2 rejects that signal.

FIX 2 — LOW-FPS HIDDEN JUMP CAN STILL BE LEARNED

If forward animation is missed, a GREEN may regain causal ownership only from
positive progression evidence:
- target switch advances exactly one
- VIEW_SCROLL / explicit progress state
- chicken is fresh
- chicken reappears roughly one lane left after scroll
- within 4.0 s of signal end

This becomes PROVISIONAL LANDING and must survive 0.75 s before success.
A crash before survival is learned as failure.

There is still NO crash fallback. A crash/reset by itself can never fabricate an
action.

NEW TELEMETRY
- green_progress_handoffs
- v5_degraded_lease_headroom
- v5_degraded_frame_margin

SAFE WINDOW LOG
  safe_window_v552_*.csv

MODELS
Keep:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do not reset them.

Read:
  V552_ANALYSIS.md
  V552_HISTORY_DO_NOT_REVISIT.md
