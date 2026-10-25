# V5.3.0 analysis — target deadlock fix

Latest V5.2.9 telemetry showed late-game TARGET hold with the locked target only ~0.13–0.25 lane ahead.
The existing landing recovery failed because `_last_target_proposal` was the same stale/consumed near lane.

V5.3.0 fixes this narrowly:
1. When locked target and normal proposal are both consumed/near, independently search detected lane centers for a center ~0.76–1.38 spacing ahead.
2. A near/consumed proposal (<0.60 spacing ahead) is not authoritative for proposal-sync, so it cannot pull a recovered target backward.
3. Stable consumed target can re-anchor after 0.28 s of fresh/stable geometry.
4. Normal GREEN target phase minimum is 0.64 spacing; verified slow-before may use 0.56. Severe near-target states remain blocked and must recover.
5. Preserve V5.2.9 learning and extend causal late failure eligibility to 3.6 s, covering the observed 3.28 s GREEN failure.

User operation: keep viewport stationary during normal play; manual movement is not a required recovery mechanism.

## Latest run measurements
- 32,546 state rows in the V5.2.9 run.
- 10,149 rows carried a TARGET-related block.
- 6,162 of those TARGET-blocked rows (~60.7%) had both locked target and nearest proposal already near/consumed (<=0.62 locked and <=0.45 proposal).
- 7,052 rows overall showed this near-target/proposal deadlock pattern.
- 1,848 rows had otherwise-valid target geometry compressed into the old 0.64-0.72 phase band that V5.2.9 hard-blocked.
- slow-before appeared only 7 rows; 4 were blocked by TARGET.

This is why V5.3.0 fixes target authority rather than lowering ML confidence again.
