import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.risk import RiskEngine
from app.upstream import predict_arrival,apply_guard
cfg=json.loads((ROOT/'config.json').read_text())
base=dict(indicator_state='CLEAR',green_confirmed=True,lane=1,effective_eta=2.,
 target_lane_distance=420.,target_lane_x=610.,target_lane_switches=1,
 viewport_rebase_count=0,chicken_fresh=True)
def attempt():
 o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
 o.update(base,dict(cx=190.,cy=731.,detected=True),10.)
 o.update({**base,'indicator_state':'WAIT'},dict(cx=320.,cy=720.,detected=True),10.6)
 return o
land={**base,'indicator_state':'WAIT','target_lane_switches':2,'target_lane_x':1030.}
o=attempt(); ev=[]
for ts in (10.9,11.1,11.3):
 ev.extend(o.update(land,dict(cx=615.,cy=731.,detected=True),ts))
assert sum(e.get('outcome_state')=='SUCCESS_FINAL' for e in ev)==1,ev
assert o.successes==1 and o.active_attempt is None and o.provisional is None
for state,x,t in [(land,615.,11.5),({**land,'viewport_rebase_count':1},190.,11.6)]:
 assert not any(e.get('kind')=='green_outcome' for e in o.update(state,dict(cx=x),t))
assert o.on_crash({'reason':'reset'},11.7) is None
assert o.successes==1 and o.failures==0
# No switch / duplicate switch / rebase cannot certify final landing.
for change in ({'target_lane_switches':1},{'target_lane_switches':3},{'viewport_rebase_count':1}):
 o=attempt(); ev=o.update({**land,**change},dict(cx=615.,cy=731.,detected=True),10.9)
 assert not any(e.get('outcome_state')=='SUCCESS_FINAL' for e in ev),ev
# Promotion also works if geometry settling had already created provisional.
o=attempt(); o.provisional=dict(o.active_attempt); o.active_attempt=None
assert o._target_arrival_success(land,dict(cx=615.,cy=731.),10.9) is None
assert o._target_arrival_success(land,dict(cx=615.,cy=731.),11.3)['outcome_state']=='SUCCESS_FINAL'
r=RiskEngine(cfg['risk'])
class Mapper:
 def lane_for(self,x): return int(x//400)
m=Mapper(); c=dict(cy=800.,h=60.)
t=dict(id=1,cx=610.,cy=100.,h=80.,age=8,vy=150.,fit_vy=600.,net_vy=500.,direction_valid=True,ts=10.)
a,i=predict_arrival([t],c,1,610.,m,r,10.)
assert 0<a<1.2,(a,i)
assert apply_guard({'green_evidence_ok':True},a,i,1.3)['upstream_prediction_blocked']
for changes in ({'cx':1300.},{'cy':1000.},{'ts':9.},{'direction_valid':False}):
 assert predict_arrival([{**t,**changes}],c,1,610.,m,r,10.)==(None,None),changes
# V5513 preserves a measured incoming trajectory across missing detections.
assert predict_arrival([{**t,'missing':1}],c,1,610.,m,r,10.)[0] == a
assert predict_arrival([{**t,'missing':1}],c,1,610.,m,r,16.) == (None,None)
for eta in (None,3.):
 s=apply_guard({'green_evidence_ok':True},eta,None,1.3)
 assert s['green_evidence_ok']
s=apply_guard({'green_evidence_ok':False},3.,1,1.3)
assert not s['green_evidence_ok']
print('PASS V554 final landing, regression/reframe immunity, exact ownership, trajectory guard')
