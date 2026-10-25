import os,sys,tempfile,importlib.util,json,time
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
root=(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]).resolve();sys.path.insert(0,str(root))
import numpy as np
from PySide6.QtWidgets import QApplication
q=QApplication.instance() or QApplication([])
spec=importlib.util.spec_from_file_location('tested_main',root/'main.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Capture:
 def __init__(self,cfg):self.frame=np.zeros((1440,2560,3),dtype=np.uint8)
 def grab(self):return self.frame
 def close(self):pass
class Clock:
 wall=time.time();perf=time.perf_counter()
 def advance(self):self.wall+=.17;self.perf+=.17
clock=Clock()
with tempfile.TemporaryDirectory() as td:
 m.ROOT=Path(td);m.ScreenCapture=Capture
 m.CFG=json.loads(json.dumps(m.CFG))
 a=m.App();a.timer.stop();a.ui.hide()
 a.lanes.centers=[190.,630.,1070.,1510.,1950.,2390.];a.lanes.spacing=440.;a.lanes.frame_width=2560
 a.lanes.update=lambda *args,**kw:None
 a.scene.update=lambda *args:dict(stable=True,pan_active=False)
 cx=[190.];cy=[731.]
 a.chicken.detect=lambda frame:dict(cx=cx[0],cy=cy[0],w=160.,h=160.,x=cx[0]-80,y=651.,detected=True,confidence=.99)
 snapshots=[]
 original=a.learner.log_state
 def logged(state,*args,**kwargs):snapshots.append((cx[0],state['target_lane_x']));original(state,*args,**kwargs)
 a.learner.log_state=logged
 def tick():
  clock.advance();cy[0]=731.+(len(snapshots)%3-1)*2
  with patch.object(m.time,'time',return_value=clock.wall),patch.object(m.time,'perf_counter',return_value=clock.perf):a.tick()
 for i in range(10):tick()
 for start,end in [(190.,630.),(630.,1070.)]:
  cx[0]=end
  # An actual owned manual move waiting for stable landing. It carries the
  # pre-action target and is independent of GREEN admission/traffic settings.
  a.passive_jump=dict(start_ts=clock.wall,start_x=start,max_x=end,
   target_dx=440.,target_x=end,viewport_rebase_count=a.viewport_rebase_count,
   target_switches_at_start=a.target_lane_lock.switches,
   features=list(a.last.get('training_features',[])),
   context=a.learner.safety_context_from_state(a.last))
  a.passive_stable_since=clock.wall-1.
  a.passive_last_x=end
  for i in range(14):tick()
  assert a.passive_jump is None,'successful landing state did not clear'
  assert abs(a.last['chicken_x']-end)<1.
  assert abs(a.last['target_lane_x']-(end+440.))<10.,a.last['target_lane_x']
  print('LANDING PASS',start,end,'next',a.last['target_lane_x'],'completed ticks',len(snapshots))
 # Third-lane viewport cut and subsequent jump must also complete updates.
 cx[0]=190.
 for i in range(14):tick()
 assert abs(a.last['chicken_x']-190.)<1.
 assert abs(a.last['target_lane_x']-630.)<10.,a.last['target_lane_x']
 print('REFRAME PASS third lane -> first lane; next',a.last['target_lane_x'])
 # The actual slot wrapper revokes stale GREEN and resumes on the next tick.
 real_tick=a.tick
 a.last.update(indicator_state='CLEAR',green_confirmed=True)
 def fail():
  a._tick_phase='injected_test_error'
  raise RuntimeError('injected test exception')
 a.tick=fail;a._run_tick()
 assert a.last['indicator_state']=='TRACK ERROR' and not a.last['green_confirmed']
 assert a._tick_error_count==1
 assert list(a.learner.folder.glob('runtime_errors_v*.log'))
 a.tick=real_tick
 clock.advance()
 with patch.object(m.time,'time',return_value=clock.wall),patch.object(m.time,'perf_counter',return_value=clock.perf):a._run_tick()
 assert a.last['indicator_state']!='TRACK ERROR'
 assert a.last['runtime_tick_errors']==1
 print('RECOVERY PASS error is visible, GREEN revoked, next update completes')
 a.timer.stop();a.green_expiry_timer.stop();a.ui.close()
 print('PASS full App.tick path after first and second landing; current coordinates and next target update')
