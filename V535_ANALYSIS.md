# V5.3.5 analysis — fullscreen third-lane reframe root cause

## Supplied V5.3.4 run

Files analysed:
- `state_20261013_043808.csv`
- `safe_window_v534_20261013_043808.csv`
- `crashes_20261013_043808.csv`
- `green_failures_20261013_043808.csv`
- `green_outcomes_20261013_043808.csv`
- `events_20261013_043808.csv`

Run length was about **23.9 minutes**.

The model emitted **8 GREEN signal IDs**. Only three acted outcomes resolved in the
outcome log: **1 success and 2 failures**.

## Root cause 1 — the normal third-lane cut was being learned as a crash

The measured lane spacing in this run was extremely stable at about **440.96 px**.
The crash log contained 9 `confirmed_progress_reset` events.

Looking at `(max_x - reset_x) / lane_spacing` separates them cleanly:

- 7 resets were about **0.90–1.11 lane spacings** backwards. These are compatible
  with a normal death/reset from the next lane back to the first lane.
- 2 resets were about **1.99 and 2.03 lane spacings** backwards. These are exactly
  the fullscreen behavior described by the user: the chicken reaches the third
  visible lane around x~1070, then the game cuts completed lanes and places the
  same chicken back around x~190 as the new first visible lane.

Those two normal progress reframes occurred at approximately:

- `1791846617.339`: max x 1068.4 -> reset x 191.8 (~1.99 lanes)
- `1791846891.886`: max x 1084.3 -> reset x 190.6 (~2.03 lanes)

The second acted GREEN failure (`signal_id=4`) was one of these progress reframes.
It was therefore a **false GREEN failure** caused by screen-coordinate regression,
not by the traffic decision itself.

The first acted GREEN failure (`signal_id=2`) reset only ~1.11 lane spacings and is
not classified as a progress reframe by the new logic. It remains a real failure
sample.

## Root cause 2 — generic scene motion had the wrong authority in fullscreen

V5.3.4 still let the generic scene-pan detector rebase all screen-space state.
That is wrong for this fullscreen game mode because moving vehicles/road animation
can look like horizontal scene translation even though the viewport has not been
manually moved.

In this run the generic detector caused:

- **149 scene/viewport rebases**
- **54 progress-scroll clusters**
- **194 target-lane relocks**
- **160 lane-phase realignments**
- `confirmed_jump_advances = 0`

This explains the reported "stuck after third lane" behavior. The model repeatedly
translated lane, target, motion and GREEN-attribution coordinates based on false
scene motion, then the chicken-anchor code had to repair the geometry again.

The real game behavior is much simpler: one deterministic cut after the third
visible lane. V5.3.5 therefore removes generic scene correlation as a coordinate
authority while fullscreen mode is enabled.

## Root cause 3 — V5.3.4 state telemetry was column-shifted

The V5.3.4 state CSV header contained **306 columns**, while every data row contained
**300 values**. Six CZN telemetry fields were added to the header but not to the row
writer:

- `czn_live_speed_reference`
- `czn_historical_speed_p95`
- `czn_historical_prior_applied`
- `czn_speed_reference_source`
- `czn_live_speed_support`
- `czn_stage_speed_reference`

This did not directly change runtime decisions, but it shifted every telemetry
column after `czn_live_ready`, making later geometry diagnostics misleading.
V5.3.5 fixes the row/header alignment and adds a regression check.

## V5.3.5 architecture change

Fullscreen mode now treats the chicken/lane geometry as authoritative for the
special progress reframe:

1. Track the freshly detected chicken and measured lane spacing.
2. A normal lane-2 death/reset is roughly one lane spacing backwards and remains
   a crash.
3. A fullscreen progress reframe must be roughly **1.55–2.45 lane spacings**
   backwards and must land near the first-lane side of the frame.
4. When detected, rebase the road grid, target lock, traffic tracks, ROI, acted
   GREEN outcome coordinates and manual-jump coordinates together.
5. Do **not** translate ChickenDetector again because it already observed the
   post-cut chicken coordinate.
6. Rebase CrashDetector before it can label the cut as a crash.
7. Preserve an acted GREEN across the cut; after coordinate translation, a
   lane-2 -> lane-3 action remains a one-lane forward displacement and can resolve
   as SUCCESS.
8. Cancel unacted GREEN permission from the pre-cut visual scene.
9. Use only a short 0.24 s settle and 0.10 s motion rewarm.
10. Raw scene-pan detections remain logged but are ignored as geometry authority in
    fullscreen mode.

## Offline separation check against this run

Using the measured ~440.96 px lane spacing, the new 1.55–2.45-lane reframe rule:

- catches both known third-lane reframes (~1.99 and ~2.03 lanes), and
- rejects all seven one-lane reset/crash events (~0.90–1.11 lanes).

This is a clean separation in the supplied telemetry rather than another global
GREEN threshold change.

## Regression tests

The following pass after the patch:

- V5.2.9 outcome/stable GREEN regression
- V5.3.0 self-advancing target regression
- V5.3.1 progress-scroll/Hardcore regression
- V5.3.2 recent-session adaptation regression
- V5.3.3 chicken-anchor geometry regression
- V5.3.4 live-speed/gap-bootstrap regression
- **V5.3.5 fullscreen reframe + acted-GREEN rebase regression**
- state telemetry header/row alignment check

## What was intentionally not changed

V5.3.5 does not lower the global GREEN threshold. The remaining genuine GREEN
failure is allowed to stay as a failure sample. The fix is focused on the actual
coordinate-frame and false-learning bugs that made third-lane progress look like
a crash and caused repeated tracking churn.
