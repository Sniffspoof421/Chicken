
import sys, numpy as np
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.motion import MotionEngine
from app.risk import RiskEngine

m=MotionEngine({
 'background_warmup_frames':1,'background_history_frames':20,
 'background_var_threshold':12,'min_blob_area':20,'max_blob_area':50000,
 'min_blob_width':3,'min_blob_height':3,'merge_kernel':3,
})
f=np.zeros((500,800,3),dtype=np.uint8)
roi=(300,20,520,420)
m.update(f,1.0,roi=roi,roi_key=2)
f2=f.copy()
f2[100:160,380:430]=255
tracks=m.update(f2,1.10,roi=roi,roi_key=2)
assert isinstance(m.last_mask,dict),type(m.last_mask)
assert m.last_mask['x0']==300 and m.last_mask['y0']==20,m.last_mask
r=RiskEngine({'lane_visibility_half_width_px':50,'clear_zone_top_ratio':.06,
              'crossing_half_height_px':30,'precision_czn_motion_ratio_max':.035})
x=r._incoming_motion_corridor(m.last_mask,405,300)
assert x['available'],x
print("V4.2.9 ROI motion mapping test PASSED")
