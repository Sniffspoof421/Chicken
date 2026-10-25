Chicken Road 2 AI Live V5.3.5 - FULLSCREEN 3-LANE REFRAME FIX

WHY THIS BUILD EXISTS
---------------------
The V5.3.4 telemetry proved the model was interpreting the game's normal
fullscreen progress behavior incorrectly.

In fullscreen mode the game behaves like this:
  first visible lane -> second visible lane -> third visible lane
  -> game cuts/discards completed lanes
  -> the same chicken is placed back near the first visible lane
  -> forward lanes remain visible

That third-lane cut is NOT a crash and NOT a manual camera pan.

V5.3.4 had two independent problems:
1. A third-lane cut such as x~1070 -> x~190 was being learned as
   confirmed_progress_reset / GREEN failure.
2. Generic scene motion from traffic generated many false viewport rebases.
   In the supplied run there were 149 viewport rebases, 194 target relocks and
   160 lane-phase realignments even though the game was being played fullscreen.

V5.3.5 FIX
----------
- Fullscreen mode no longer lets generic scene correlation move the coordinate
  frame. Raw scene-pan detections are telemetry only.
- A dedicated chicken/lane-spacing gate recognizes the real third-lane cut:
  approximately TWO lane spacings backwards, landing near the first visible lane.
- One-lane death/reset behavior remains a crash and continues to train UNSAFE.
- On a valid progress reframe, lane grid, target, traffic tracks, ROI, GREEN
  outcome coordinates and manual-jump coordinates are rebased together.
- ChickenDetector itself is NOT translated a second time because it has already
  seen the chicken at its new first-lane screen position.
- CrashDetector is rebased before it can learn the normal cut as a death.
- An acted GREEN is preserved across the reframe and can resolve as SUCCESS.
- Unacted GREEN permission from the old visual scene is cancelled.
- Only a short 0.24 s settle / 0.10 s motion rewarm is used.
- V5.3.4 live-speed/gap fix, V5.3.3 chicken anchor and V5.3.2 session adaptation
  are retained.

IMPORTANT PLAY MODE
-------------------
Use the game in fullscreen as described above. Do NOT manually drag/recentre the
viewport while this fullscreen mode is enabled. The model now expects the game's
own deterministic third-lane cut and handles it automatically.

MODEL FILES
-----------
Keep the existing V5.3.2-compatible model files if you have them:
  data\models\online_state_v532.joblib
  data\models\safe_window_v532.joblib

Do not rename them. The new build prevents new false progress-reframe failures
from being learned. Current-session adaptation still starts fresh each launch.

START
-----
Run: start_v535.bat

NEW TELEMETRY
-------------
- fullscreen_reframe_active
- fullscreen_reframe_count
- fullscreen_reframe_shift_px
- fullscreen_reframe_shift_lanes
- fullscreen_reframe_age
- raw_scene_pan_ignored

The V5.3.4 state-CSV alignment bug is also fixed: the six new CZN telemetry
columns now have matching row values, so columns after czn_live_ready no longer
shift out of alignment.
