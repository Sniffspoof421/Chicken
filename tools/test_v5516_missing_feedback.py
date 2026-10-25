import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.safe_window import SafeWindowPredictor
cfg=json.loads((ROOT/'config.json').read_text())
def setup():
 o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
 o.update(dict(indicator_state='CLEAR',green_confirmed=True,lane=2,
  target_lane_distance=440.,target_lane_x=1070.,target_lane_switches=52,
  chicken_fresh=True,v5_feature_vector=[0.]*len(SafeWindowPredictor.FEATURE_NAMES)),
  dict(cx=630.,cy=731.,detected=True),100.)
 o.observe_input(dict(control='space',timestamp=100.465,cue_within_deadline=True,
  signal_id=1,foreground=1,cue_foreground=1,green_display_deadline=100.5,
  target_lane_switches=52,chicken_x=630.),100.5)
 return o
# Signal 9 timing and positions, relative to GREEN start (rounded from state CSV).
o=setup()
for dt,x,y in [(1.07,691.57,737.62),(1.39,660.09,785.63)]:
 ch=dict(cx=x,cy=y,detected=True)
 o.confirm_input_movement(ch);assert o._expire_missing_attempt(ch,100+dt) is None
 o._attempt_progress(ch,100+dt)
for dt in [1.73,2.14]:
 assert o._expire_missing_attempt(None,100+dt) is None
# Fresh reset observations arrive before continuous-loss timeout.
assert o._expire_missing_attempt(dict(cx=191.65,detected=True),102.55) is None
ev=o.on_crash(dict(event_time=102.55,reason='confirmed_progress_reset',
 max_x=1659.5,reset_x=188.88),103.2)
assert ev['outcome']=='failure',ev
with tempfile.TemporaryDirectory() as td:
 learner=SafeWindowPredictor(Path(td),cfg['safe_window_v5'])
 assert learner.record_green_feedback(ev)==1
 assert learner.feedback_failures==1
assert o.on_crash(dict(event_time=103.3),103.3) is None
# Short loss after an old action must not instantly resolve UNKNOWN.
o=setup()
assert o._expire_missing_attempt(None,101.8) is None
assert o._expire_missing_attempt(None,102.2) is None
assert o._expire_missing_attempt(dict(cx=630.,detected=True),102.3) is None
assert o._expire_missing_attempt(None,102.4) is None
# Absolute attempt cap prevents recurring loss keeping JUMPING forever.
assert o._expire_missing_attempt(None,104.)['outcome']=='unknown'
# Stale detections do not restart the absence clock.
o=setup();assert o._expire_missing_attempt(None,100.8) is None
assert o._expire_missing_attempt(dict(cx=630.,detected=False),102.1)['outcome']=='unknown'
# Actual post-input multiple jumps still cannot train as one GREEN failure.
o=setup();o.confirm_input_movement(dict(cx=1400.,cy=731.,detected=True))
o.active_attempt['input_movement_seen']=True
assert o.on_crash(dict(event_time=102.,max_x=1400.,reset_x=190.),102.)['outcome']=='chained_unvalidated'
# No movement never trains a failure.
o=setup();assert o.on_crash(dict(event_time=102.,max_x=1659.),102.)['outcome']=='unknown'
print('PASS recorded signal-9 timing, scoped peak, feedback, dedup, continuous loss, expiry and chain exclusion')
