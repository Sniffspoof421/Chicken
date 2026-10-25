Chicken Road 2 AI Live V5.4.7
RUNTIME RECOVERY + CLICK-vs-CV TIMING SPLIT

RUN
  start_v547.bat

WHAT THE V5.4.6 RUN PROVED

1. GREEN starvation was caused by the reaction budget, not a lack of gaps.
   - Only one GREEN signal was registered in ~15.3 minutes.
   - SafeWindow produced only two decision=1 frames.
   - Dynamic-gap reaction budget averaged ~0.99 s and reached ~1.14 s.
   - Dynamic-gap required ETA averaged ~2.04 s.
   - This happened because delayed chicken-motion confirmation was being treated
     as if it were the user's reaction time.

2. The user clicks immediately.
   The 1-2 second delay in telemetry is mostly:
   - game movement/animation,
   - stronger anti-wobble confirmation,
   - frame cadence / chicken detection.
   It must be used for causal outcome attribution, NOT pre-jump safety ETA.

3. A real GREEN jump was discarded from learning.
   The single brief GREEN was followed by chicken movement roughly:
       x ~564 -> x ~1065
   and the target advanced with ARRIVED.
   Yet green_acted stayed 0 because TRACK/MOTION REWARM set generic hold flags.
   V5.4.6 incorrectly treated those hold flags as non-causal camera movement.

4. Runtime stalls are visible in telemetry.
   State updates stop for:
   - ~23.4 seconds after the first lane transition,
   - later ~13.8, ~14.6, ~15.3 and ~14.3 second gaps.
   The recording shows the game continues running.
   V5.4.7 recovers stale screen-space state when the loop resumes and removes
   periodic full model serialization from the hot loop.

5. Chicken identity can drift between lanes.
   The supplied state moved from a stable ~631 px chicken location to ~460 px
   for many seconds. ~460 is an ambiguous between-lane position.
   V5.4.7 prevents a nearby colour blob in the middle of two lanes from stealing
   the chicken identity.

V5.4.7 CHANGES

A. SEPARATE INPUT RESPONSE FROM CV ACTION CONFIRMATION
Safety ETA now uses a fixed bounded input-response allowance:
  EASY    0.30 s
  NORMAL  0.34 s
  HARD    0.40 s
  EXTREME 0.46 s

The longer 2.30 s GREEN attribution grace remains ONLY for connecting eventual
robust chicken movement to the signal.

Historical movement-confirmation delay is still logged as:
  dynamic_gap_observed_action_delay
but it no longer enlarges dynamic_gap_required_eta.

B. REAL JUMPS CAN BE ATTRIBUTED DURING TRACK/MOTION REWARM
The outcome tracker now blocks action ownership only for:
  - actual scene pan,
  - actual progress-scroll/fullscreen reframe,
  - stale chicken detection.

Generic viewport_hold / vision_hold caused by motion ROI rewarm no longer destroys
a real GREEN action.

C. CHICKEN MID-LANE IDENTITY GUARD
  prefer_near_fraction: 0.42 -> 0.24
  ambiguous mid-lane band: 0.28 to 0.70 lane

A candidate in that band is held as pending instead of becoming the confirmed
chicken. A genuine landing close to one full lane away is still confirmed using
the existing multi-frame jump confirmation.

D. RUNTIME GAP RECOVERY
If the main loop resumes after >=1.50 s without a tick:
  - stale chicken identity is reacquired,
  - target lock is reset from the current frame,
  - motion background/ROI is rebuilt,
  - short-lived gap evidence is invalidated,
  - long-term learned traffic/model data are preserved.

New telemetry:
  runtime_tick_gap_seconds
  runtime_gap_recoveries
  runtime_gap_recovery_active
  chicken_candidate_count
  chicken_midlane_rejected
  chicken_midlane_rejections

E. REMOVE SYNCHRONOUS MODEL SERIALIZATION FROM LIVE HOT LOOP
Periodic telemetry CSV flush continues.
Full OnlineLearner/SafeWindow model serialization is disabled during live play
and still runs on clean program exit.

This avoids a large disk/joblib operation from freezing the UI/analysis loop.

PRESERVED
- V5.4.5 centered post-pass GO-NOW timing
- V5.4.4 EASY/NORMAL/HARD/EXTREME mode switching
- V5.4.3 adaptive verified-gap lease
- V5.4.2 anti-wobble action ownership
- V5.3.8 causal one-GREEN/one-jump outcomes
- V5.3.5 fullscreen third-lane reframe
- current-session traffic speed guard
- physical verified-gap ML override

MODELS
Keep:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do not reset them.

LOG
  safe_window_v547_*.csv
