Chicken Road 2 AI Live V5.3.8 - CAUSAL GREEN OUTCOME FIX

Run: start_v538.bat

ROOT CAUSES FIXED
1) REMOVED FABRICATED GREEN FAILURES
- V5.3.7 still had a legacy crash fallback that looked back up to 6 seconds.
- It could invent action_start_ts = green_end even when no GREEN action was observed.
- V5.3.8 never creates a GREEN failure from crash geometry alone.
- No observed action -> no GREEN failure label.

2) ONE GREEN OWNS ONE JUMP
- If progress exceeds the one-jump chain envelope (>1.55 lane steps), later
  crash/reset is CHAINED_UNVALIDATED, never a GREEN failure.
- This guard runs BEFORE regression/failure logic in active and provisional states.
- The same protection is applied when CrashDetector fires before outcome polling.

3) FULLSCREEN 3-LANE REFRAME USES A RECENT PEAK
- The game may be sampled as 1070 -> 700 -> 190 at low FPS.
- V5.3.7 only compared the previous frame and could miss that cut.
- V5.3.8 compares the new first-lane position to the recent peak over ~1.6 s.
- A normal lane-2 -> lane-1 death (~1 lane) is still not classified as progress.

4) SECONDARY REFRAME SAFETY NET
- If CrashDetector sees a ~2-lane progress reset before the visual gate fires,
  main.py converts it to fullscreen progress BEFORE crash/unsafe/GREEN-failure learning.
- The false crash counter is undone and screen-space state is rebased once.

5) ONE-TIME GREEN FAILURE MEMORY CLEANUP
- Policy version is now 538.
- Old GREEN-only failure counters, source failure ETA floors, and SafeWindow
  direct failure prototypes are cleared once when loading a pre-538 model.
- Validated GREEN successes, long-term traffic model, vehicle/type behavior,
  generic crash memory, pattern/gap history and speed learning are preserved.

CONFIG
- post_green_action_grace_seconds remains 0.65 s.
- late_observation_window_seconds reduced to 1.80 s (timing diagnostics only).
- fullscreen_reframe_peak_window_seconds = 1.60 s.

TELEMETRY
- SafeWindow log is now safe_window_v538_*.csv.
- Existing fullscreen_reframe_count/shift telemetry remains.
- Outcome status also tracks ignored crash fallbacks and multi-jump unvalidated events.

MODEL FILES
Keep/copy:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do NOT delete the models. V5.3.8 performs the one-time policy cleanup automatically.
