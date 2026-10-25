import sys,json,tempfile,copy,ast,collections,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np,joblib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.slow_profile import build_slow_profile
from app.checkpoint import idle_checkpoint_due
from app.learning import OnlineLearner
cfg=json.loads((ROOT/'config.json').read_text())
def profile(events,seg=1,now=100.,directional=True):
 return build_slow_profile(events,0,seg,.22,5.,6,now,directional=directional)
def pair(t,forward='S',following='F',gap=1.,seg=1,cls='M'):
 return [dict(ts=t,forward_class=forward,**{'class':cls},token=cls,segment=seg,gap=None),
         dict(ts=t+gap,forward_class=following,**{'class':'M'},token='M',segment=seg,gap=gap)]
# Lateral/EMA disagreement: physically slow anchors and fast followers use the
# same class definition as the live slow geometry, not generic total speed.
p=profile({0:pair(50.)});assert p['support']==1 and p['p_fast_after_slow']==1.,p
p=profile({0:pair(50.,forward='M',cls='S')});assert p['support']==0,p
# Reset boundaries never bridge two different runs.
e=pair(50.);e[1]['segment']=2
assert profile({0:e})['support']==0
# Missing forward_class in old saved events falls back without losing history.
e=pair(50.,following='M',gap=1.6,cls='S')
for r in e:r.pop('forward_class')
assert profile({0:e})['support']==1
# A mature recent lane pattern can supersede old, incompatible local traffic.
e=[]
for i in range(12):e+=pair(i*3.,gap=.6,following='F',seg=0)
for i in range(6):e+=pair(80.+i*2.5,gap=1.6,following='M',seg=1)
p=profile({0:e},now=99.)
assert p['source']=='recent-lane' and p['p25_gap']>1.5 and p['p_fast_after_slow']==0,p
# Sparse new examples do not override mature history.
p=profile({0:e[:-2]},now=99.)
assert p['source']=='lane' and p['p25_gap']<1.,p
# Recent dangerous fast followers are retained; adaptation is not SAFE-only.
e=[r for i in range(6) for r in pair(80.+i*2.5,gap=.6,following='F')]
p=profile({0:e},now=99.)
assert p['source']=='recent-lane' and p['p_fast_after_slow']==1,p
# Checkpoints do not run during active permission, jumps or reacquisition.
idle=dict(indicator_state='ETA HOLD',chicken_fresh=True,chicken_anchor_stable=True,
 processing_healthy=True)
assert idle_checkpoint_due(idle,100.,0.)
for change in [dict(indicator_state='CLEAR'),dict(green_active=1),dict(v5_decision=True),
 dict(green_evidence_ok=True),dict(rearm_needed=1),dict(chicken_fresh=False),dict(game_progress_scroll_context=True)]:
 assert not idle_checkpoint_due({**idle,**change},100.,0.),change
assert not idle_checkpoint_due(idle,89.,0.)
# Atomic persistence: interrupted serialization leaves the existing model intact.
with tempfile.TemporaryDirectory() as td:
 l=OnlineLearner(Path(td)/'data'/'sessions',cfg['learning'])
 l.events[0].extend(pair(50.));l.pattern_event_n=2
 assert l.flush(save_model=True) is True
 before=l.state_path.read_bytes()
 saved=joblib.load(l.state_path);assert saved['slow_profile_policy']==559
 with patch('app.learning.joblib.dump',side_effect=OSError('injected disk failure')):
  assert l.flush(save_model=True) is False
 assert l.state_path.read_bytes()==before
 assert l.last_model_save_ok is False and 'injected disk failure' in l.last_model_save_error
# Background writer captures the old state coherently while live counters advance.
import threading
with tempfile.TemporaryDirectory() as td:
 l=OnlineLearner(Path(td)/'data'/'sessions',cfg['learning'])
 l.observation_n=100
 l.events[0].extend(pair(50.))
 entered=threading.Event();release=threading.Event();original_dump=joblib.dump
 def paused_dump(payload,path):
  entered.set()
  assert release.wait(3.)
  return original_dump(payload,path)
 with patch('app.learning.joblib.dump',side_effect=paused_dump):
  assert l.request_checkpoint()
  assert entered.wait(3.)
  l.observation_n=101
  l.events[0][0]['forward_class']='F'
  assert not l.request_checkpoint() # no concurrent writes to the same target
  release.set();l.wait_for_checkpoint()
 assert joblib.load(l.state_path)['observation_n']==100
 assert joblib.load(l.state_path)['events'][0][0]['forward_class']=='S'
 assert l.events[0][0]['forward_class']=='F'
 assert l.observation_n==101
 assert l.flush(save_model=True)
 assert joblib.load(l.state_path)['observation_n']==101
print('PASS V559 forward speed, followers, recent context, legacy fallback, idle/atomic persistence')
# Optional tests against the supplied historical model and exact original method.
if len(sys.argv)>1:
 model=joblib.load(Path(sys.argv[1])/'online_state_v532.joblib')
 oldroot=Path(sys.argv[2])
 tree=ast.parse((oldroot/'app/learning.py').read_text())
 cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='OnlineLearner')
 fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='slow_anchor_profile')
 ns=dict(np=np,defaultdict=collections.defaultdict)
 exec(compile(ast.Module(body=[fn],type_ignores=[]),'<original slow profile>','exec'),ns)
 obj=SimpleNamespace(events=model['events'],min_valid_gap_seconds=.22,max_valid_gap_seconds=5.)
 original=copy.deepcopy(model['events'])
 for lane in model['events']:
  a=ns['slow_anchor_profile'](obj,lane,6)
  b=build_slow_profile(model['events'],lane,999,.22,5.,6,time.time(),directional=False)
  for k,value in a.items():
   if isinstance(value,float):assert abs(value-b[k])<1e-12,(lane,k,value,b[k])
   else:assert value==b[k],(lane,k,value,b[k])
 assert model['events']==original
 n=sum(e.get('forward_class') in ('S','M','F') and e.get('forward_class')!=e.get('class')
  for hist in model['events'].values() for e in hist if e.get('token')!='<RESET>')
 assert n==185,n
 print('PASS supplied model: 185 class disagreements; non-slow profiles match original; history unchanged')
