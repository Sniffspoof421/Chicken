Chicken Road 2 AI Live V5.4.1 - SESSION-FAST ETA GUARD + JUMP HANDOFF

Run: start_v541.bat

WHAT THE V5.4.0 RUN PROVED
- The one recorded GREEN failure was a real one-lane crash.
- It came from the V5.4.0 sustained observed-clear shortcut at ~1.43 s ETA.
- That ETA used a 392 px/s startup/live reference.
- Earlier in the same run, confirmed vehicle crossings had already shown much
  faster traffic (session forward-speed P80 ~732 px/s).
- The 180 s live window had gone quiet, so the model forgot the session's fast
  traffic and treated an untracked lane as safer than it was.

V5.4.1 FIXES

1) SESSION-FAST SPEED GUARD FOR OBSERVED-CLEAR ONLY
- Confirmed crossing events from THIS app session are retained independently of
  the rolling 180 s live window.
- After >=12 valid session events, an 80th-percentile forward-speed guard is used.
- Guard is capped at 800 px/s and includes a small margin.
- Observed-clear policy ETA is scaled conservatively by this guard.
- Verified busy->clear dynamic gaps are NOT scaled; they retain direct timing.

2) REMOVE THE UNSAFE 1.40 s SHORTCUT
- Strong sustained observed-clear no longer lowers the physical ETA requirement.
- Minimum strong observed-clear ETA is 1.62 s after the session-speed guard.
- Required support raised 20 -> 36.
- Clear dwell >=1.10 s.
- Gap P25 >=1.75 s.
- Physical heuristic >=0.92.
- Raw risk <=12.
- Motion corridor <=0.025.
- MOG <=0.035.
- This path may still bypass collapsed ML when physics are strong, but it may
  not bypass the physical time requirement.

3) VERIFIED GAP REMAINS THE SHORT-OPPORTUNITY PATH
- V5.3.7/V5.3.9 verified busy->clear fast path is unchanged.
- Strong live verified gaps can still bypass stale ML.
- All hard hazards and action-lease rules remain authoritative.

4) REAL JUMP HANDOFF FIX
- V5.4.0 waited for the literal target lock reason ARRIVED.
- In the supplied successful jumps, target_lane_switches advanced while the
  reason was already HOLD_SAME.
- V5.4.1 uses target ownership advance + one-lane geometry + old-target match.
- The genuine failed jump did NOT advance target ownership at landing, so it is
  not falsely credited as success.
- This releases JUMPING/next-lane analysis much earlier on actual successes.

5) EXISTING SAFETY FIXES PRESERVED
- Causal GREEN outcome ownership.
- One GREEN = one jump.
- Fullscreen 3-lane recent-peak reframe.
- No fabricated 6-second GREEN crash attribution.
- Physical verified override.
- Missing-CV timeout is UNKNOWN, not failure.
- Hard motion/MOG/vehicle/target/processing vetoes remain immediate.

NEW TELEMETRY
safe_window_v541_*.csv:
- policy_eta
- observed_clear_guard_eta
- session_speed_guard_reference
- session_speed_support

state CSV:
- czn_session_speed_support
- czn_session_speed_guard_reference
- czn_observed_clear_speed_reference

MODEL FILES
Keep:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do not delete them. The real V5.4.0 failure remains useful learned evidence.
