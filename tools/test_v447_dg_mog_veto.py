import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.risk import RiskEngine
ROOT=Path(__file__).resolve().parents[1]
cfg=json.loads((ROOT/'config.json').read_text())['risk']
r=RiskEngine(cfg)
# Final corridor mask is clear, but raw MOG says 20% of the tracked ROI is active.
h,w=400,300
mask=np.zeros((h,w),np.uint8)
mog=np.zeros((h,w),np.uint8); mog[:80,:]=255
diff=np.zeros((h,w),np.uint8)
view=r._incoming_motion_corridor({
 'mask':mask,'mog_mask':mog,'diff_mask':diff,
 'x0':0,'y0':0,'full_h':h,'full_w':w,'ready':True
},150,330)
assert view['clear'] is True,view
assert view['mog_global_ratio']>.10,view
assert cfg['dynamic_gap_max_mog_ratio']==.10
assert cfg['dynamic_gap_max_preceding_busy_seconds']==1.40
print('V4.4.7 DG independent MOG veto PASSED',view['mog_global_ratio'])
