# V5.2.0 analysis and redesign

## Why V5.1 did not solve the positioning failure
The latest session showed that the recovery system itself was churning target state: hundreds of target switches/relocks and self-heals occurred. Zero vehicle tracks was being interpreted as a broken ROI even when the lane could genuinely be empty.

More importantly, chicken identity was unstable. The state history repeatedly moved from the real chicken around x~630 to a recurring false candidate around x~1084-1085 and then snapped back. Of 199 large forward coordinate changes, 167 (~88%) reverted toward the old position within about one second. A single false color match therefore looked like a completed one-lane jump and dragged the target lane, ROI, progress learner, and GREEN attribution with it.

The formally learned GREEN failure in the same run contained this signature: baseline chicken x~634, action-start x~1085, then end x~634 with essentially zero net forward progress. That outcome is not reliable evidence of a real jump and should not be allowed to train the safe-window model.

## V5.2 corrections
1. Lane-relative chicken identity gate. Large moves are pending until they persist across multiple frames.
2. Nearby-identity preference. A distant high color-score candidate cannot instantly replace a stable nearby chicken.
3. Confirmed-jump target follow. Once the move is confirmed, target/ROI follows the new chicken lane immediately.
4. Empty-lane tolerance. `active_tracks == 0` is diagnostic, not a self-heal trigger.
5. Geometry-based recovery. Re-anchor only after sustained mismatch between the locked target and the chicken-relative lane proposal.
6. Clean safe-window labels. Candidate labels are dropped across target switches, pans, rewarm/desync periods, and stale chicken observations.
7. Asymmetric slow vehicle logic. `slow-before` and `slow-after` are separate features and policies. Slow-before can be accepted with sufficient approach/follower timing; after-slow is guarded unless the learned headway profile and follower ETA are strong.
8. Longer future horizon. V5.2 labels safety over 1.65 seconds instead of learning from very short clear snapshots.
9. Fresh V5.2 safe learner. The old V5.1 safe-window model is intentionally not migrated because its labels were contaminated by identity/ROI errors.

## Model persistence
Useful V5.1 traffic/pattern/crash history can migrate from `online_state_v510.joblib` to `online_state_v520.joblib`. The supervised outcome/safe-memory state that depended on unreliable jump identity is reset by migration. The safe-window learner starts independently as `safe_window_v52.joblib`.
