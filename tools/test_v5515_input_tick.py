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
 # Queue a real input event through App.tick, before chicken movement.
 a.outcome=type(a.outcome)(m.CFG['outcome_learning'])
 cue=dict(indicator_state='CLEAR',green_confirmed=True,lane=1,
          target_lane_distance=440.,target_lane_x=630.,target_lane_switches=3,
          viewport_rebase_count=0,chicken_fresh=True)
 a.outcome.update(cue,dict(cx=190.,cy=731.,detected=True),clock.wall)
 a.input_audit.events.put(dict(control='space',timestamp=clock.wall+.05,
     cue_within_deadline=True,signal_id=1,foreground=100,cue_foreground=100,
     green_display_deadline=clock.wall+.5,target_lane_switches=3,chicken_x=190.))
 cx[0]=225.;tick()
 assert a.outcome.active_attempt is not None
 assert a.outcome.active_attempt['input_owned']
 assert a.outcome.active_attempt['input_movement_seen']
 assert a.input_audit.events.empty()
 a.timer.stop();a.green_expiry_timer.stop();a.input_audit.close();a.ui.close()
 print('PASS App.tick drains input before scene processing and confirms early movement')
