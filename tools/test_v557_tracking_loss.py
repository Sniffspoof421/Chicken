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
 def logged(state,*args,**kwargs):snapshots.append((cx[0],state.get('target_lane_x')));original(state,*args,**kwargs)
 a.learner.log_state=logged
 def tick():
  clock.advance();cy[0]=731.+(len(snapshots)%3-1)*2
  with patch.object(m.time,'time',return_value=clock.wall),patch.object(m.time,'perf_counter',return_value=clock.perf):a.tick()
 # Each scenario exercises the complete application tick, with no GUI loop
 # or real capture needed. Any exception fails the test directly.
 live_detector=a.chicken.detect
 centers=list(a.lanes.centers)
 def lost_grid():
  a.lanes.centers=[];a.lanes.spacing=None
 def restore_grid():
  a.lanes.centers=list(centers);a.lanes.spacing=440.
 def steps(n,label):
  before=len(snapshots)
  for i in range(n):tick()
  assert len(snapshots)==before+n,(label,len(snapshots)-before,n)
  assert a._tick_error_count==0,(label,a._tick_error_count)
  print('PASS',label,'completed updates',n)
 a.chicken.detect=lambda frame:None
 lost_grid()
 steps(12,'startup without chicken or lane grid')
 assert not a.last.get('green_confirmed',False)
 restore_grid()
 steps(12,'lane grid ready but no chicken')
 assert not a.last.get('green_confirmed',False)
 a.chicken.detect=live_detector
 cx[0]=190.
 steps(16,'chicken reacquired at first lane')
 assert abs(a.last['chicken_x']-190.)<1.
 assert abs(a.last['target_lane_x']-630.)<10.
 a.chicken.detect=lambda frame:None
 steps(400,'68 seconds of chicken loss beyond every hold timeout')
 assert not a.last.get('green_confirmed',False)
 assert not a.last['chicken_fresh']
 a.chicken.detect=live_detector
 cx[0]=630.
 steps(16,'reacquired at moved chicken position')
 assert abs(a.last['chicken_x']-630.)<1.
 assert abs(a.last['target_lane_x']-1070.)<10.
 lost_grid()
 steps(12,'chicken present while lane grid disappears')
 assert not a.last.get('green_confirmed',False)
 a.chicken.detect=lambda frame:None
 steps(16,'chicken and lane grid both disappear after a landing')
 assert not a.last.get('green_confirmed',False)
 restore_grid()
 steps(12,'lane grid returns before chicken')
 a.chicken.detect=live_detector
 cx[0]=190.
 steps(16,'tracking automatically resumes at current first-lane position')
 assert abs(a.last['chicken_x']-190.)<1.
 assert abs(a.last['target_lane_x']-630.)<10.
 assert a.last['indicator_state']!='TRACK ERROR'
 assert not list(a.learner.folder.glob('runtime_errors_v*.log'))
 a.timer.stop();a.green_expiry_timer.stop();a.ui.close()
 print('PASS V557 full tick tracking-loss and reacquisition regression')
