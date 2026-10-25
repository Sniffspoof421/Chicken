Chicken Road 2 AI Live V5.4.4 - HYSTERETIC DIFFICULTY MODE SWITCHING

Run: start_v544.bat

WHY V5.4.3 GOT STUCK
- The supplied 63-minute run had 15 GREEN signal IDs but only 1 acted GREEN.
- There was a long ~25-minute interval (about minute 35 to 60) with no V5 GREEN decision.
- The adaptive regime layer was not describing the game reliably: regime_samples
  was usually zero because traffic pauses created new regimes.
- At the same time the dynamic-gap predictor kept 65% long-history weight and
  allowed recent gaps to improve the lower bound by only 12%. Hard traffic
  therefore contaminated later easier traffic, while hardening could also lag.
- The fixed strong-physical P25 requirement was also backwards for hard modes:
  a hard game naturally has a low historical P25, so even a rare large current
  gap could be rejected for not looking like an easy-game distribution.

V5.4.4 ARCHITECTURE

1) FOUR EXPLICIT DIFFICULTY MODES
- EASY / NORMAL / HARD / EXTREME.
- Score uses live motion headway, speed, density and gap volatility.
- It does not require tracker crossing events to keep working.
- Hardening switches quickly after sustained evidence.
- Easing requires longer evidence so one lucky gap cannot loosen the model.
- Hysteresis prevents boundary flapping.

2) TRAFFIC PAUSE NO LONGER RESETS REGIME
- A quiet interval is not a new traffic distribution.
- Regime changes are kept for actual statistical speed/headway shifts.

3) ASYMMETRIC RECENT-GAP ADAPTATION
Old V5.4.3:
  lower_bound = 65% long history + 35% recent
  recent improvement capped at 1.12x old history

V5.4.4:
- Hardening: recent lower gaps get dominant weight quickly.
- Easing: after mode hysteresis confirms improvement, recent larger gaps may
  move the lower bound much more decisively.
- Mode-specific upward caps:
    EASY 1.45x / NORMAL 1.35x / HARD 1.24x / EXTREME 1.16x
- Mode-specific downward floors also allow rapid conservative hardening.

4) MODE-SPECIFIC DYNAMIC GAP VERIFIER
RiskEngine changes support/confidence/quantile/max-clear-age by mode.
Defaults:
- EASY: support 8, confidence 0.62, P25 quantile ~25
- NORMAL: support 9, confidence 0.66, P22
- HARD: support 10, confidence 0.70, P18
- EXTREME: support 12, confidence 0.74, P15

5) HARD MODES NO LONGER REQUIRE EASY-GAME HISTORICAL P25
SafeWindow strong-physical profiles use stricter CURRENT evidence as difficulty
rises, while historical P25 minimum decreases:
- EASY: P25 >=1.75, conf >=0.64, lease >=0.24
- NORMAL: P25 >=1.55, conf >=0.68, lease >=0.30
- HARD: P25 >=1.30, conf >=0.72, lease >=0.34
- EXTREME: P25 >=1.05, conf >=0.76, lease >=0.38
Harder modes also tighten raw-risk, motion and MOG limits.

This is intentional: HARD traffic has shorter normal gaps. A rare current large
gap should be judged by strong current-cycle evidence, not rejected because the
historical average is short.

6) OBSERVED-CLEAR SAFETY
- HARD and EXTREME never use sustained observed-clear shortcut.
- They require verified busy->clear traffic evidence.
- EASY/NORMAL retain the strict guarded observed-clear path.

7) EXISTING FIXES PRESERVED
- One GREEN = one jump.
- Anti-wobble jump ownership.
- Causal outcome learning.
- 3-lane fullscreen reframe handling.
- Current-session speed guard.
- Cycle-aware GREEN rearm.
- Early motion-rise GREEN cancellation.
- V5.4.3 standard 0.42 lease semantics remain compatible in NORMAL mode.

HUD / TELEMETRY
- HUD V5 line now shows M E/N/H/E for difficulty mode.
- state CSV adds difficulty_mode, difficulty_mode_score, mode switches,
  gap/speed/density components, recent-vs-long dynamic-gap lower bounds,
  recent weighting and regime direction.
- safe_window_v544_*.csv includes mode and mode score.

MODEL FILES
Keep your existing:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib
Do not delete them. V5.4.4 changes live regime control, not long-term model identity.
