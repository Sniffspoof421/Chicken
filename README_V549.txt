Chicken Road 2 AI Live V5.4.9
V5.4.7 PRESERVED + DEGRADED-FPS RECOVERY + UNIQUE MANUAL LEARNING

RUN
  start_v549.bat

IMPORTANT
V5.4.9 is rebuilt from V5.4.7, NOT from V5.4.8.

The V5.4.8 GREEN lease increases, third-jump lease penalty, and global rapid-GREEN
presentation guard are NOT carried forward.

WHY V5.4.8 PRODUCED ALMOST NO GREEN

The supplied V5.4.8 run had:
- median processing FPS ~2.35
- V5.4.7 run median processing FPS ~6.5
- processing_healthy true on only ~2.9% of V5.4.8 state rows
- 4,596 / 4,742 SafeWindow rows blocked by PROCESSING
- only 5 SafeWindow decision frames
- only 1 registered GREEN signal

The old processing floor was 2.8 FPS, so the decision engine was globally disabled
even though the low-FPS verified-gap telemetry still contained strong opportunities.

V5.4.9 FIX 1 — DEGRADED FPS IS NOT GLOBAL NO-GREEN

Normal performance floor remains 2.8 FPS for diagnostics.

Stable processing >=2.0 FPS is now allowed in degraded mode.

Safety is NOT relaxed blindly:
SafeWindow's existing lease logic already scales the required extra presentation
margin by the actual frame rate:

    frame_margin = 1/FPS + 0.04

At ~2.35 FPS this is ~0.47 s of extra action lease.

In the supplied V5.4.8 state, ignoring only the fixed PROCESSING veto, roughly:
- 26 strong verified physical frames
- ~20 distinct gap episodes

still met basic current-lane physical/lease conditions.

V5.4.9 FIX 2 — V5.4.7 GREEN LOGIC RESTORED EXACTLY

Strong physical extra lease:
- EASY 0.18
- NORMAL 0.22
- HARD 0.26
- EXTREME 0.30

Standard lease:
- EASY 0.34
- NORMAL 0.42
- HARD 0.46
- EXTREME 0.50

At low FPS the dynamic frame margin automatically dominates these numbers.

V5.4.8's stricter 0.45-0.60 physical floors are removed.
V5.4.8's third-success extra lease/settle is removed.
V5.4.8's rolling two-GREEN/20-second presentation limit is removed.

V5.4.7's cycle-aware rearm remains.

V5.4.9 FIX 3 — MANUAL SUCCESS LEARNING WITHOUT MODEL DEPENDENCE

The model still learns autonomously from:
- traffic crossings
- speed/type observations
- busy->clear gap history
- traffic sequence patterns
- crash contexts
- validated GREEN outcomes
- SafeWindow/current physics

User jumps are only supplemental training.

V5.4.8 manual success learning overcounted badly:
- 126 reported manual successes
- only 51 target-lane ownership switches
- successful-lane streak reached 75

This meant many duplicate/false SAFE labels were being created.

V5.4.9 learns a manual/no-GREEN success only when:
- the pre-jump target geometry was valid
- the landing is stable and fresh
- viewport is unchanged
- target ownership advanced EXACTLY one switch
- that target-switch ID has not already been credited

At most one manual SAFE label can therefore be created per real target ownership
advance.

Manual success is low weight:
- SAFE context weight 0.32
- supervised SAFE weight 0.38

If FPS is already in degraded mode, the cheap SAFE-context memory is kept but the
heavier classifier partial_fit is skipped for that jump. This prevents manual
training from worsening runtime performance.

V5.4.9 FIX 4 — FASTER POST-JUMP RECOVERY

V5.4.7 already force-reacquired a stale chicken after 1.0 s.

V5.4.9 shortens this to ~0.60 s specifically when:
- target is WAIT_CHICKEN_LAND, or
- the chicken detector is rejecting an ambiguous between-lane candidate.

This prevents the old chicken position from surviving too long after a jump while
keeping the mid-lane false-identity protection.

NEW TELEMETRY
- processing_degraded
- processing_green_floor_fps
- post_jump_reacquire_active
- post_jump_reacquire_age_required
- manual_success_duplicate_skips
- last_manual_success_switch
- manual_success_context_only

SAFE WINDOW LOG
  safe_window_v549_*.csv

MODELS
Keep:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do NOT delete/reset them.
