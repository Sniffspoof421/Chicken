"""Real tracker-to-predictor regression; synthetic detections, real association."""
import json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.motion import MotionEngine
from app.risk import RiskEngine
from app.upstream import predict_arrival,apply_guard
cfg=json.loads((ROOT/'config.json').read_text())
risk=RiskEngine(cfg['risk']);engine=MotionEngine(cfg['tracking'])
class Mapper:
 def lane_for(self,x):return 2 if 900<x<1250 else 1
mapper=Mapper();chicken=dict(cx=630.,cy=731.,h=160.)
frame=np.zeros((1,1,3),np.uint8);detections=[]
engine._detections=lambda *args,**kwargs:detections

def tick(t,y=None):
 detections[:]=[] if y is None else [dict(cx=1100.,cy=y,w=120.,h=200.,area=24000.,mean_h=0.,mean_s=0.,mean_v=100.)]
 return engine.update(frame,timestamp=t,roi_key='lane2')
def arrival(tracks,t):return predict_arrival(tracks,chicken,2,1070.,mapper,risk,t)
tick(10.,150.)
public=tick(10.15,240.)
assert 'history' not in public[0] # autonomous learning contract is unchanged
assert arrival(public,10.15)==(None,None) # old caller loses early trajectory
eta,tid=arrival(engine.prediction_tracks(),10.15)
assert eta is not None and eta<1.,(eta,tid)
assert not apply_guard(dict(green_evidence_ok=True),eta,tid,1.4)['green_evidence_ok']
tick(10.30,330.)
assert engine.prediction_tracks()[0]['direction_valid']
assert tick(10.45)==[] # empty foreground should not erase a measured threat
eta,tid=arrival(engine.prediction_tracks(),10.70)
assert eta==0. and tid is not None,(eta,tid)
# Later disappearance expires by rear exit, not an indefinite block.
assert arrival(engine.prediction_tracks(),12.)==(None,None)
# No retained trajectory can migrate across ROI reset.
engine.force_reset(roi_key='lane3')
assert engine.prediction_tracks()==[]
# Unmeasured single-frame blobs never gain an extrapolated velocity.
tick(20.,200.);tick(20.15)
assert arrival(engine.prediction_tracks(),20.2)==(None,None)
# Existing tracker expiry also bounds retention, including a slow vehicle.
for i in range(engine.max_missing+1):tick(20.3+i*.1)
assert engine.prediction_tracks()==[]
print('PASS real two-observation history, missing mature threat, rear-exit expiry, ROI reset, immature loss and tracker expiry')
