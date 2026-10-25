import json,sys
from pathlib import Path
import numpy as np
ROOT=(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0,str(ROOT))
from app.motion import MotionEngine
cfg=json.loads((ROOT/'config.json').read_text())
frame=np.zeros((1,1,3),np.uint8)
def setup():
 e=MotionEngine(cfg['tracking']);detections=[]
 e._detections=lambda *args,**kwargs:detections
 def tick(t,y=None):
  detections[:]=[] if y is None else [dict(cx=661.5,cy=y,w=180.,h=180.,area=30000.,mean_h=0.,mean_s=0.,mean_v=100.)]
  return e.update(frame,timestamp=t,roi_key=1)
 return e,tick
# Positions/times from signal 6's fragmented incoming track history, followed
# by its next observed same-column detection. Synthetic boxes, not video.
e,tick=setup();tick(10.,86.5);tick(10.0789741,201.)
tick(10.20);tick(10.30);tick(10.4139354,605.)
assert len(e.tracks)==1,[(k,v['cy']) for k,v in e.tracks.items()]
t=next(iter(e.tracks.values()));assert t['age']==3 and t['direction_valid']
# A slow vehicle moving 40px over .8s must be measured as 50px/s, regardless
# of how recently the loop processed an intervening empty frame.
e,tick=setup();tick(20.,100.)
for i in range(1,8):tick(20.+i*.1)
tick(20.8,140.)
t=next(iter(e.tracks.values()));assert abs(t['fit_vy']-50.)<.001,t['fit_vy']
assert abs(t['accel']-t['speed']/.8)<.001,t['accel']
print('PASS fast track survives observed-time gap; slow speed uses elapsed observation time')
from app.input_audit import input_record
s=dict(indicator_state='CLEAR',green_display_deadline=10.3,visible_green_signal_id=4)
assert input_record('space',10.2,1.,s)['cue_within_deadline']
assert not input_record('space',10.4,1.,s)['cue_within_deadline']
assert input_record('space',10.2,1.,s)['signal_id']==4
print('PASS diagnostic input cue/deadline attribution; no outcome labels inferred')
