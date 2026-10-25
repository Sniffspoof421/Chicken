Chicken Road 2 AI Live V5.4.0 - JUMP HANDOFF + ACTIONABLE GREEN

Run: start_v540.bat

WHAT THE V5.3.9 LOGS PROVED
- Signal 3 started with chicken x~193 and target x~608.
- The chicken moved to x~630, target lock switched to the next lane (ARRIVED),
  and target became x~1072. That is a completed one-lane jump.
- OutcomeTracker did not close the success because it waited for extra fresh
  chicken frames. CV then went stale and the UI stayed JUMPING for ~4.2 s.
- When chicken later returned left, the already-completed jump was wrongly
  recorded as jump_regression_reset.
- All six visible GREEN IDs in the run were only one logged frame long.
- 5,000+ observed-clear states were blocked by the old 1.58 s universal ETA
  floor even though live traffic gap evidence was mature.

V5.4.0 FIXES

1) TARGET-ARRIVAL SUCCESS HANDOFF
- An acted GREEN stores the target lane and target-switch counter at signal time.
- If StableNextLane later reports ARRIVED, target switch increments, viewport
  frame is unchanged, and chicken landed inside the expected one-jump envelope,
  the GREEN closes as SUCCESS immediately.
- It no longer waits for several extra CV frames after the lane lock has already
  proven the landing.
- Normal rearm is still kept briefly before the next GREEN.

2) NO MULTI-SECOND JUMPING DEADLOCK
- If chicken CV disappears during an active attempt and no landing proof appears
  within 1.25 s, the outcome becomes UNKNOWN, never failure.
- This releases next-lane analysis instead of remaining JUMPING for 4-6 s.

3) ACTIONABLE GREEN DISPLAY HOLD
- A committed GREEN gets at least 0.75 s of visible permission while the
  underlying physical hard gate remains safe.
- A one-frame provenance/ETA-policy flip cannot instantly erase GREEN.
- Visible vehicle, uncertain vehicle, target/viewport/processing failure,
  motion/MOG hazard, slow guard, physical ETA floor, and crash-memory hard veto
  still cancel immediately.

4) RESTORE MATURE OBSERVED-CLEAR OPPORTUNITIES
- The old universal observed-clear floor of 1.58 s was introduced from failure
  data that later proved heavily contaminated by attribution bugs.
- V5.4.0 does NOT lower this floor globally.
- It permits ~1.40 s ETA only when live evidence is mature and unusually clean:
    current clear >= 1.00 s
    motion-gap support >= 20
    gap P25 >= 1.70 s
    physical heuristic >= 0.90
    raw risk <= 18
    motion corridor <= 0.04
    MOG <= 0.055
- This uses current physical traffic evidence, not stale ML optimism.

5) ONE-TIME FALSE FAILURE CLEANUP
- Policy version 540 clears pre-540 GREEN-only failure counters/source ETA floors
  and SafeWindow direct failure prototypes once.
- Valid successes, vehicle/type learning, pattern/gap history, speed learning,
  long-term retrospective model and generic crash memory are preserved.

NEW TELEMETRY
SafeWindow:
- sustained_observed_override
- active_green_hold_override

State:
- green_target_arrival_successes
- v5_sustained_observed_override
- v5_active_green_hold_override

SafeWindow files are now named safe_window_v540_*.csv.

MODEL FILES
Keep/copy:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do not delete them. V5.4.0 performs the policy cleanup automatically.
