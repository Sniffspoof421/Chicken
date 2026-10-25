import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.missed_green import MissedGreenRearm
cfg=json.loads((ROOT/'config.json').read_text())
base=dict(indicator_state='CLEAR',green_confirmed=True,lane=1,
 target_lane_switches=1,viewport_rebase_count=0,target_lane_x=630.,
 target_lane_distance=440.,chicken_fresh=True,chicken_anchor_stable=True,
 target_lane_geometry_ok=True,motion_corridor_available=True,
 motion_corridor_clear=True,dynamic_gap_cycle_id=10,scene_pan_stable=True,
 motion_preceding_busy_duration=.3,green_rearm_min_busy=.16)
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
ev=o.update(base,dict(cx=190.),100.)
assert any(e.get('kind')=='green_signal_started' for e in ev)
o.update({**base,'indicator_state':'WAIT'},dict(cx=190.),100.5)
ev=o.update({**base,'indicator_state':'WAIT'},dict(cx=190.),103.)
assert any(e.get('kind')=='green_unacted' for e in ev),ev
# A changed cycle ID no longer bypasses the existing missed-cue cooldown.
assert not o.green_display_allowed(103.1,11,state={**base,'dynamic_gap_cycle_id':11})
# Waiting out time, or changing the counter without observing occupancy, is insufficient.
assert not o.green_display_allowed(105.1,12,state={**base,'dynamic_gap_cycle_id':12})
# A real new occupancy after the miss followed by a mature clear passage rearms.
assert not o.green_display_allowed(105.2,12,state={**base,'dynamic_gap_cycle_id':12,'motion_corridor_clear':False})
assert o.green_display_allowed(105.6,13,state={**base,'dynamic_gap_cycle_id':13})
# Existing true GREEN can continue, and owned jumps retain the one-jump block.
o.current_signal={'signal_id':1};assert o.green_display_allowed(106.,13,state=base)
o.current_signal=None;o.active_attempt={};assert not o.green_display_allowed(106.,13,state=base)
# Short motion noise cannot rearm; rewarm/invalid coordinates cannot manufacture a passage.
g=MissedGreenRearm();sig=dict(target_switches_at_signal=1,viewport_rebase_at_signal=0)
g.missed(sig,100.)
assert not g.allowed({**base,'motion_corridor_clear':False},101.,2.)
assert not g.allowed({**base,'dynamic_gap_cycle_id':11,'motion_preceding_busy_duration':.05},103.,2.)
assert not g.allowed({**base,'dynamic_gap_cycle_id':12,'motion_corridor_clear':False,'tracking_rewarm':True},104.,2.)
assert not g.allowed({**base,'dynamic_gap_cycle_id':13},105.,2.)
# A genuine new target starts independently; it does not inherit old-lane blackout.
assert g.allowed({**base,'target_lane_switches':2},105.1,2.)
# A nearby reset with no observed action is recorded UNKNOWN, never failure training.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.update(base,dict(cx=190.),100.)
x=o.on_crash(dict(event_time=100.8,reason='confirmed_progress_reset'))
assert x['outcome']=='unknown' and x['unknown_reason']=='reset_without_observed_action'
assert o.failures==0
print('PASS V558 missed cue cooldown, fresh passage, noise rejection, target ownership and reset audit')
