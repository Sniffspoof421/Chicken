import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.safe_window import SafeWindowPredictor
cfg=json.loads((ROOT/'config.json').read_text())
def setup():
 o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
 o.update(dict(indicator_state='CLEAR',green_confirmed=True,lane=2,
  target_lane_distance=440.,target_lane_x=1070.,target_lane_switches=30,
  chicken_fresh=True,v5_feature_vector=[0.]*len(SafeWindowPredictor.FEATURE_NAMES)),
  dict(cx=630.,cy=731.,detected=True),100.)
 o.observe_input(dict(control='space',timestamp=100.55,cue_within_deadline=True,
  signal_id=1,foreground=1,cue_foreground=1,green_display_deadline=100.6,
  target_lane_switches=30,chicken_x=630.),100.6)
 return o
def ch(x,y=731.):return dict(cx=x,cy=y,detected=True)
def fall(o):
 o.confirm_input_movement(ch(659.,746.))
 o.confirm_input_movement(ch(637.,764.))
# Rounded fresh observations from signal 3.
o=setup();fall(o)
assert o._early_input_reset({},ch(191.56),102.53) is None
e=o._early_input_reset({},ch(192.45,732.46),102.95)
assert e['outcome']=='failure' and e['failure_type']=='early_fall_stable_reset',e
with tempfile.TemporaryDirectory() as td:
 learner=SafeWindowPredictor(Path(td),cfg['safe_window_v5'])
 assert learner.record_green_feedback(e)==1 and learner.feedback_failures==1
assert o._early_input_reset({},ch(190.),103.2) is None
# Camera events, upward jump, late reset, one observation, substantial forward
# progress and screen rebasing must never create this failure label.
for mode in ['pan','rebase','upward','late','progress','stale']:
 o=setup()
 if mode=='upward':o.confirm_input_movement(ch(659.,680.))
 else:fall(o)
 if mode=='rebase':o.rebase_viewport(-440.)
 if mode=='progress':o.confirm_input_movement(ch(1070.,731.))
 state={'scene_pan_active':True} if mode=='pan' else {}
 sample=dict(ch(190.),detected=False) if mode=='stale' else ch(190.)
 t=120. if mode=='late' else 102.5
 assert o._early_input_reset(state,sample,t) is None,mode
 assert o._early_input_reset(state,sample,t+.4) is None,mode
print('PASS recorded early reset, learner increment, dedup, camera, upward, late, forward and stale exclusions')

# Recorded state sequence, including raw pan ignored by fullscreen mode.
o=setup();events=[]
for row in json.loads((ROOT/'tools/fixture_v5516_signal3.json').read_text()):
 state=dict(row['state'],indicator_state='HOLD',green_confirmed=False)
 o.confirm_input_movement(row['chicken'])
 events+=o.update(state,row['chicken'],100+row['dt'])
failures=[e for e in events if e.get('outcome')=='failure']
assert len(failures)==1 and failures[0]['crash_reason']=='input_owned_early_fall_reset',events
print('PASS full outcome.update replay including ignored fullscreen raw-pan telemetry')
