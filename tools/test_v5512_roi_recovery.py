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
 # Reproduce the logged starvation: crop locked during airborne y=679.
 from app.crossing import crossing_occupancy
 a.motion_roi_rect=(357,50,903,824)
 a.motion_roi_lane=1
 a.motion_roi_frame_shape=(1440,2560)
 old=a.motion_roi_generation
 a.motion.force_reset(roi_key=(1,old))
 # Normal resting y=731 needs coverage through y=839, beyond old crop.
 for i in range(10):tick()
 assert a.motion_roi_rect[3]>=839,a.motion_roi_rect
 assert a.motion_roi_generation==old+1,(old,a.motion_roi_generation)
 assert a.last['crossing_motion_available'],a.last.get('crossing_motion_reason')
 assert a.last['crossing_motion_clear']
 assert a.last['motion_ready']
 recovered=a.motion_roi_rect
 for i in range(40):tick()
 assert a.motion_roi_generation==old+1,'resting jitter repeatedly reset tracking'
 assert a.motion_roi_rect==recovered
 assert a.last['runtime_tick_errors']==0
 print('PASS actual App.tick expands airborne crop once, warms, sees crossing, stays stable')
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
 print('PASS ROI recovery integration and tick error recovery')
