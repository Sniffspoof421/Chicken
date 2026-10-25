# V5.3.3 analysis — chicken-authoritative geometry

## Evidence from the V5.3.2 run

Input telemetry: `state_20261013_003516.csv`, `safe_window_v532_20261013_003516.csv`, session/events/crash/outcome logs.

- State rows: 3,129.
- Target distance outside the existing GREEN geometry band (0.64–1.30 lane): 575 rows.
  - too close: 237;
  - too far: 338.
- 555 of those bad-target rows occurred with a freshly detected chicken and with neither active scene-pan nor progress-scroll context.
- `target_proposal_error_ratio >= 0.30` occurred 772 times; `>= 0.50` occurred 741 times.
- Long stale-target episodes were visible even in nominally stable scenes, including ~53.5 s, ~32.9 s and ~25.0 s contiguous episodes outside the GREEN band.
- Target-lock reasons were dominated by `HOLD_SAME` (1,881) and `HOLD_HYSTERESIS` (1,141), showing that hysteresis could preserve the wrong physical lane for too long.
- The run recorded one resolved successful GREEN jump with forward displacement ~444.25 px, consistent with a one-lane transition in this capture.

## Root causes fixed

1. The road detector could find the correct periodic spacing but choose the wrong phase; target calculations then inherited that phase error.
2. `StableNextLane` repaired targets that were much too far ahead, but did not symmetrically repair consumed targets around ~0.25–0.60 lane ahead when a better one-spacing proposal existed.
3. Consumed-target and confirmed-teleport paths could advance while the chicken was still moving, which could skip a lane or leave the ROI ahead of the actual landing.
4. After a geometry correction, short-lived clear/motion evidence from the old corridor could survive unless explicitly invalidated.

## V5.3.3 architecture

`fresh chicken -> stable landing dwell -> lane phase -> next lane -> bounded traffic ROI -> motion/tracks -> ETA/risk -> GREEN gate`

The chicken is now the spatial authority. The road markings still determine lane spacing, but a stable landed chicken corrects periodic phase. The target is then exactly the first lane centre ahead. GREEN geometry additionally requires the chicken anchor to be stable.

## What V5.3.3 deliberately does not change

- It does not lower risk/ETA thresholds simply to create more GREENs.
- It preserves V5.3.2 two-timescale current-session adaptation.
- It preserves long-term vehicle, crash and follower memory.
- It does not treat a normal automatic game scroll as a user action.

## Validation

Added `tools/test_v533_chicken_anchor_geometry.py` covering:
- half-lane phase correction to a stable chicken;
- no churn when already aligned;
- repair of a consumed stale target to the true one-spacing next lane;
- rejection of non-authoritative proposals.

The V5.3.0 target, V5.3.1 progress-scroll, V5.3.2 migration/adaptation and V5.3.3 geometry tests pass together. Historical non-migration regression tests were also rerun with the project root on `PYTHONPATH`; version-specific old migration tests are expected to assert their historical state filenames and are not a current-build compatibility criterion.
