Chicken Road 2 AI Live V5.4.3 - ADAPTIVE VERIFIED-GAP LEASE

Run: start_v543.bat

ROOT CAUSE FROM V5.4.2 RUN
- Run duration: ~38 minutes.
- 179 verified physical gap cycles were observed.
- Only 16 cycles produced GREEN.
- 342 verified SafeWindow frames were rejected as ACTION LEASE.
- RiskEngine already included jump time + safety + learned reaction budget +
  measured pipeline latency in dynamic_gap_required_eta (~1.81 s average).
- Learned reaction budget was already at its configured 0.72 s maximum.
- V5.4.2 then added another flat 0.55 s SafeWindow lease, effectively
  requiring ~2.36 s before GREEN. This double-counted margin and starved GREEN.

V5.4.3 FIX
1) TWO-TIER VERIFIED LEASE
- Strong live physical gap: 0.32 s extra presentation reserve.
- Standard / ML-only verified gap: 0.42 s extra reserve.
- Both still sit on top of RiskEngine's full required ETA.
- FPS frame margin and RiskEngine lease floor remain authoritative.

2) STRONG PHYSICAL TIER IS STRICT
The 0.32 s tier is available only when the existing V5.4.2 strong physical
criteria pass (confidence, gap support, P25, heuristic probability, low raw
risk, low corridor motion, low MOG, no hard hazard).

3) OBSERVED-CLEAR IS NOT RELAXED
- V5.4.0's unsafe short observed-clear path remains closed.
- V5.4.1 session-speed guard remains intact.
- This build recovers missed GREENs only from verified busy->clear gaps.

4) V5.4.2 SAFETY FIXES REMAIN
- Lane-scaled anti-jitter action ownership.
- Cycle-aware unacted GREEN rearm.
- Early GREEN motion-rise cancellation.
- Causal one-GREEN/one-jump outcome learning.
- Fullscreen third-lane reframe handling.

REPLAY OF SUPPLIED V5.4.2 TELEMETRY
- Current V5.4.2: ~16 verified cycles admitted.
- V5.4.3 two-tier rule: ~49 verified cycles qualify.
- Roughly 33 additional strong verified cycles are recovered.
- Weak/marginal verified states keep the larger 0.42 s reserve.

NEW TELEMETRY
SafeWindow v543 log includes:
- verified_gap_physical_min_action_lease
- verified_gap_lease_tier
- verified_gap_selected_lease_required

State CSV includes the same selected lease diagnostics.

MODEL FILES
Keep/copy:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib
Do not delete the models. No learning-policy reset is required for V5.4.3.
