import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.learning import OnlineLearner
from app.safe_window import SafeWindowPredictor
cfg=json.loads((ROOT/'config.json').read_text())
def setup():
 o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
 o.update(dict(indicator_state='CLEAR',green_confirmed=True,lane=1,
  target_lane_distance=440.,target_lane_x=630.,target_lane_switches=3,
  chicken_fresh=True,v5_feature_vector=[0.]*len(SafeWindowPredictor.FEATURE_NAMES)),
  dict(cx=190.,cy=731.,detected=True),100.)
 return o
def record(ts,valid,deadline=101.69):
 return dict(control='space',timestamp=ts,cue_within_deadline=valid,
  signal_id=1 if valid else None,foreground=1,cue_foreground=1,
  green_display_deadline=deadline if valid else None,
  target_lane_switches=3,chicken_x=190.)
# Recorded signal-1 timing: logical end precedes press but painted cue valid.
o=setup();o.expire_display(100.548)
assert o.observe_input(record(100.6445,True),100.7)
o.confirm_input_movement(dict(cx=630.,cy=790.,detected=True))
ev=o.on_crash(dict(event_time=102.562,reason='jump_regression_reset',reset_x=190.),102.562)
assert ev['input_validated_deadline']==101.69 and ev['outcome']=='failure'
with tempfile.TemporaryDirectory() as td:
 l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
 assert l.record_green_outcome(ev)==1
 assert l.green_source_failures[ev.get('eta_source','unknown')]==1
# Both recorded late input cases must cancel the cue before delayed CV movement.
for end,press in [(.5296,.6014),(.2236,.4913)]:
 o=setup();o.expire_display(100+end)
 assert o.observe_input(record(100+press,False),100+press+.05) is None
 assert o.signal_diagnostics[-1]['unknown_reason']=='recorded_input_outside_green'
 assert not any([o.current_signal,o.pending_signal,o.recent_expired_signal])
 state=dict(indicator_state='HOLD',green_confirmed=False,target_lane_switches=3)
 o.update(state,dict(cx=630.,cy=790.,detected=True),102.)
 assert o.active_attempt is None
 assert o.on_crash(dict(event_time=102.4,reason='reset'),102.4) is None
# Stale input and focus mismatch cannot revoke a cue.
for change in [dict(foreground=2),dict(timestamp=99.)]:
 o=setup();rec=record(100.2,False);rec.update(change)
 o.observe_input(rec,100.3);assert o.current_signal is not None
print('PASS valid-input learner agreement, recorded off-GREEN precedence, no late CV reclaim, stale/focus exclusions')
