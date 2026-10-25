Chicken Road 2 AI Live — V5.3.3
Chicken-Authoritative Geometry

Run: start_v533.bat

WHY THIS BUILD EXISTS
The V5.3.2 telemetry showed that the AI could keep a stale target-lane geometry even while the chicken was freshly visible. That means vehicle tracking, ETA and GREEN logic could be internally consistent but calculated for the wrong physical lane. V5.3.3 fixes the geometry first; it does not loosen GREEN thresholds to hide the problem.

WHAT CHANGED
1. Stable chicken = authoritative geometry anchor. The lane grid is allowed to re-phase only after a freshly detected chicken remains horizontally stable for a short landing dwell. It never chases the chicken while the sprite is jumping.
2. Lane-grid phase repair. If road markings lock to the correct spacing but the wrong periodic phase, the grid is shifted so the landed chicken sits on a lane centre. Spacing is never changed by this correction.
3. Immediate next-lane re-anchor. After a phase repair, the target becomes the first lane centre ahead of the chicken. ROI, vehicle motion and ETA are therefore computed from the same chicken-relative origin.
4. Symmetric stale-target repair. A target that is too close/consumed is now repaired just like a target that is too far ahead. The old logic mainly handled the too-far case.
5. No premature lane advancement. Consumed-target recovery, confirmed-jump advancement and landing recovery now wait for the chicken to settle before advancing.
6. Safe corridor reset on geometry change. A chicken-driven re-anchor clears only short-lived corridor/motion evidence so an old lane cannot donate a fake clear window to the new lane. Long-term vehicle/crash learning is preserved.
7. GREEN is geometry-gated. target_green_geometry_ok now also requires a stable chicken anchor. There is no GREEN while the chicken is between lanes or while its anchor is unresolved.
8. New telemetry: analysis_anchor_x/y, chicken_anchor_stable/age/dx, lane_phase_error_ratio, lane_phase_shift_px, lane_phase_realigns, lane_phase_bias_px, lane_phase_sync_reason and lane_phase_reanchored.
9. V5.3.2 two-timescale learning is preserved unchanged: current-session evidence can outweigh stale long-term statistics, while long-term crash/type memory remains a prior.

MODEL FILES / PRESERVING TRAINING
V5.3.3 intentionally keeps the V5.3.2 learning-state filenames because the ML feature schema did not change:
  online_state_v532.joblib
  safe_window_v532.joblib
If you already have trained V5.3.2 copies, place them in data\models before launch. Do not copy .tmp files. This avoids throwing away training just because the geometry layer changed.

HOW TO USE
- Do not manually drag/recentre the game during normal play.
- Let the game perform its own automatic progress scroll.
- After a jump or scroll, the model briefly waits for the chicken to settle, re-aligns geometry if needed, then resumes next-lane analysis.
- In the compact display, A✓ means the chicken anchor is settled; A… means it is moving/reacquiring and GREEN geometry is intentionally blocked.

IMPORTANT SAFETY/QUALITY BEHAVIOUR
The existing hard vetoes remain: visible/uncertain vehicle, active viewport motion, processing failure, MOG/motion hazard, slow-after/follower danger, physical ETA failure, learned GREEN-failure memory and one-jump rearm.
