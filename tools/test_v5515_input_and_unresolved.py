import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.risk import RiskEngine
from app.upstream import unresolved_vehicle,apply_unresolved_guard,predict_arrival
from app.safe_window import SafeWindowPredictor
cfg=json.loads((ROOT/'config.json').read_text())
base=dict(indicator_state='CLEAR',green_confirmed=True,lane=1,target_lane_distance=440.,
          target_lane_x=630.,target_lane_switches=3,viewport_rebase_count=0,chicken_fresh=True,
          v5_feature_vector=[0.]*len(SafeWindowPredictor.FEATURE_NAMES))
def setup():
 o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
 o.update(base,dict(cx=190.,cy=731.,detected=True),10.)
 rec=dict(control='space',timestamp=10.2,cue_within_deadline=True,signal_id=1,
          foreground=100,cue_foreground=100,green_display_deadline=10.5,
          target_lane_switches=3,chicken_x=190.)
 return o,rec
# A press alone is not a training label.
o,rec=setup();assert o.observe_input(rec,10.3)
ev=o.on_crash(dict(event_time=10.8,reason='reset'),10.8)
assert ev['outcome']=='unknown'
# Early motion < old 24% threshold plus recorded input plus confirmed reset.
o,rec=setup();o.observe_input(rec,10.3)
o.confirm_input_movement(dict(cx=225.,cy=747.,detected=True))
ev=o.on_crash(dict(event_time=10.8,reason='confirmed_progress_reset',max_x=225.,reset_x=190.),10.8)
assert ev['outcome']=='failure' and not ev['weak_action_attribution']
with tempfile.TemporaryDirectory() as td:
 learner=SafeWindowPredictor(Path(td),cfg['safe_window_v5'])
 assert learner.record_green_feedback(ev)==1
 assert learner.feedback_failures==1
assert ev['action_start_ts']==10.2 and o.on_crash(dict(event_time=11.,reason='reset'),11.) is None
# Ineligible events do not acquire an attempt.
for change in [dict(control='left_mouse'),dict(cue_within_deadline=False),dict(timestamp=10.6),
               dict(foreground=101),dict(signal_id=2),dict(target_lane_switches=4)]:
 o,rec=setup();rec.update(change);assert o.observe_input(rec,10.7) is None
# Additional input invalidates one-jump ownership.
o,rec=setup();o.observe_input(rec,10.3);o.observe_input(dict(rec,timestamp=10.4),10.4)
assert o.active_attempt is None and o.signal_diagnostics[-1]['outcome']=='unknown'
# Explicit pan does not silently erase input ownership or train a false crash.
o,rec=setup();o.observe_input(rec,10.3);o.invalidate_viewport(dict(cx=90.,cy=731.))
assert o.signal_diagnostics[-1]['unknown_reason']=='input_attempt_viewport_invalidated'
# First video's logged large unresolved vehicle fragment.
r=RiskEngine(cfg['risk']);ch=dict(cx=633.,cy=733.,h=160.)
t=dict(id=612,cx=1102.5,cy=620.,w=307.,h=516.,ts=249639.3867569,age=1,
       missing=3,direction_valid=False)
now=249639.8799946
assert unresolved_vehicle([t],ch,1072.75,r,now,1.43)==612
assert not apply_unresolved_guard(dict(green_evidence_ok=True),612,enforce=True)['green_evidence_ok']
assert unresolved_vehicle([t],ch,1072.75,r,now+1.5,1.43) is None
for change in [dict(cx=1600.),dict(cy=1500.),dict(w=20.,h=14.),dict(direction_valid=True)]:
 assert unresolved_vehicle([dict(t,**change)],ch,1072.75,r,now,1.43) is None
# Earliest of two incoming measured vehicles is always used.
class Mapper:
 def lane_for(self,x):return 2
tracks=[dict(t,id=1,cy=50.,h=100.,ts=now,age=5,missing=0,matched=True,direction_valid=True,vy=100.,fit_vy=100.,net_vy=100.),
        dict(t,id=2,cy=300.,h=100.,ts=now,age=5,missing=0,matched=True,direction_valid=True,vy=900.,fit_vy=900.,net_vy=900.)]
assert predict_arrival(tracks,ch,2,1072.75,Mapper(),r,now)[1]==2
print('PASS input ownership, early crash, exclusions, duplicate prevention, viewport audit, recorded uncertainty hold, expiry and convoy minimum')

assert apply_unresolved_guard(dict(green_evidence_ok=True),612)['green_evidence_ok']
