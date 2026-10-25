from pathlib import Path
import json, sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.lane import LaneMapper
from app.target_lane import StableNextLane

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Reproduce the half-lane phase failure seen in the V5.3.2 telemetry.
# Spacing is correct, but the periodic grid is 0.5 lane away from a landed
# chicken. The chicken must become the authoritative phase origin.
lm=LaneMapper(cfg['lanes'])
lm.frame_width=2560
lm.frame_height=1248
lm.spacing=440.0
lm.centers=[300.0,740.0,1180.0,1620.0,2060.0]
lm.boundaries=[80.0,520.0,960.0,1400.0,1840.0,2280.0]

diag=lm.align_phase_to_chicken(
    520.0,
    min_fraction=cfg['tracking']['lane_phase_realign_min_fraction'],
    max_fraction=cfg['tracking']['lane_phase_realign_max_fraction'],
)
assert diag['changed'], diag
assert abs(diag['ratio']-.5) < 1e-9, diag
assert abs(lm.centers[0]-520.0) < 1e-9, lm.centers
nxt=lm.next_lanes(520.0,1)
assert nxt and abs(nxt[0][1]-960.0) < 1e-9, nxt
assert abs((nxt[0][1]-520.0)/lm.spacing-1.0) < 1e-9, nxt

# Already aligned chicken must not create repeated phase churn.
diag2=lm.align_phase_to_chicken(
    522.0,
    min_fraction=cfg['tracking']['lane_phase_realign_min_fraction'],
    max_fraction=cfg['tracking']['lane_phase_realign_max_fraction'],
)
assert not diag2['changed'] and diag2['reason']=='ALIGNED', diag2

# 2) Symmetric target repair. V5.3.1/5.3.2 only repaired a target that was too
# far ahead. A consumed target ~0.45 spacing ahead could survive while the
# current chicken-relative proposal sat at the real one-spacing lane.
lock=StableNextLane(
    arrival_fraction=.22,
    switch_min_seconds=.18,
    min_ahead_fraction=.10,
    max_ahead_fraction=1.55,
    reanchor_fraction=.18,
    authoritative_min_fraction=cfg['tracking']['target_authoritative_min_fraction'],
    authoritative_max_fraction=cfg['tracking']['target_authoritative_max_fraction'],
    sync_improvement_fraction=cfg['tracking']['target_sync_improvement_fraction'],
)
lock._set(1,720.0,0.0,'TEST',count_switch=False)  # 200 px ahead = 0.455 lane
out=lock.update([(2,960.0)],520.0,440.0,1.0)
assert out==(2,960.0), out
assert lock.last_reason=='CHICKEN_SYNC', lock.last_reason

# A proposal that is itself not near one spacing must NOT override hysteresis.
lock2=StableNextLane(
    authoritative_min_fraction=.72,
    authoritative_max_fraction=1.28,
    sync_improvement_fraction=.14,
)
lock2._set(1,720.0,0.0,'TEST',count_switch=False)
out2=lock2.update([(2,750.0)],520.0,440.0,1.0)
assert out2==(1,720.0), out2
assert lock2.last_reason=='HOLD_HYSTERESIS', lock2.last_reason

print('PASS v533 chicken-authoritative lane phase + symmetric target sync')
