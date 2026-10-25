from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.target_lane import StableNextLane

cfg=json.loads((ROOT/'config.json').read_text())
tc=cfg['tracking']

# Reproduce the late-game deadlock geometry from the V5.2.9 run:
# chicken ~190 px, stale locked/proposed lane ~251 px, spacing ~441 px.
lock=StableNextLane(arrival_fraction=.22,switch_min_seconds=.18,min_ahead_fraction=.10,max_ahead_fraction=1.55,reanchor_fraction=.18)
lock._set(0,251.64,0.0,'TEST',count_switch=False)
centers=[251.64,674.57,1115.5]
alt=lock.forward_recovery_candidate(
    centers,190.25,441.0,
    min_ratio=tc['consumed_target_next_min_fraction'],
    max_ratio=tc['consumed_target_next_max_fraction'],
    min_advance_fraction=tc['consumed_target_min_advance_fraction'],
)
assert alt is not None, 'consumed target must find an independent forward center'
assert alt[0] == 1 and abs(alt[1]-674.57) < 1e-6, alt
# Feeding that independent proposal to the existing target state machine should
# advance immediately because the old target has been reached/consumed.
out=lock.update([alt],190.25,441.0,1.0)
assert out[0] == 1 and abs(out[1]-674.57) < 1e-6, out
assert lock.last_reason == 'ARRIVED', lock.last_reason

# Do not skip a lane when the current target is merely camera-compressed but
# not consumed: next center is too far ahead to qualify as recovery.
lock2=StableNextLane()
lock2._set(0,450.0,0.0,'TEST',count_switch=False)
alt2=lock2.forward_recovery_candidate([450.0,891.0],190.0,441.0,
    min_ratio=tc['consumed_target_next_min_fraction'],
    max_ratio=tc['consumed_target_next_max_fraction'],
    min_advance_fraction=tc['consumed_target_min_advance_fraction'])
assert alt2 is None, alt2

assert tc['proposal_sync_min_ahead_fraction'] >= .60
assert tc['target_green_slow_before_min_ahead_fraction'] < tc['target_green_min_ahead_fraction']
assert cfg['learning']['late_green_causal_max_seconds'] >= 3.28
print('PASS v530 self-advancing consumed target + protected proposal sync')
