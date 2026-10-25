Chicken Road 2 AI Live — V5.3.4
Root-Cause CZN / Live-Gap Fix

Run: start_v534.bat

WHY V5.3.3 PRODUCED NO GREEN
The latest telemetry showed zero V5 hard-safe frames. Two gates formed a deterministic deadlock:

1. Old historical/stage speed was forced back into the physical CZN speed reference as a max. The target lane had ~635 px of visible upstream road, but the speed reference stayed 700–741 px/s. Clear-zone ETA therefore stayed only ~0.75–0.90 s while V5 requires >=1.08 s. No clear-zone GREEN was mathematically possible.

2. Strong busy->clear motion evidence was allowed by the later physical override, but the earlier live-gap gate could reject the state first when CZN crossing evidence was sparse. The override was therefore unreachable during some bootstrap periods.

WHAT V5.3.4 CHANGES
- Current-session speed is authoritative for physical CZN ETA.
- Historical speed is only a bounded cold-start prior and rapidly loses authority once live evidence appears.
- Long-term stage speed remains useful for difficulty/context, but no longer hard-maxes current physical ETA.
- Strong, mature busy->clear target-lane motion can bootstrap live-gap verification before sparse tracker crossing events mature.
- Weak motion evidence is NOT enough; existing visible vehicle, uncertain vehicle, motion/MOG, target, processing, slow/follower, crash-memory and ETA vetoes remain.
- V5.3.3 chicken-authoritative geometry remains unchanged.
- V5.3.2 current-session ML adaptation remains unchanged.

NEW TELEMETRY
- czn_live_speed_reference
- czn_historical_speed_p95
- czn_historical_prior_applied
- czn_speed_reference_source
- czn_live_speed_support
- czn_stage_speed_reference
- safe_window_v534_*.csv

PRESERVE TRAINING
Keep/copy your trained V5.3.2 model files into data\models:
  online_state_v532.joblib
  safe_window_v532.joblib

The filenames intentionally stay v532 because the ML feature schema did not change.

HOW TO USE
- Start with start_v534.bat.
- Do not manually drag/recentre the game during normal automatic progress scrolling.
- A✓ still means the chicken anchor is settled and target geometry is valid.
- V5.3.4 should begin accumulating v5_session_train_n once real hard-safe windows appear; it should no longer remain permanently at 0 because of the stale CZN ETA wall.

See V534_ANALYSIS.md for the telemetry breakdown and offline replay.
