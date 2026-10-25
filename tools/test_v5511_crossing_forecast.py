import csv
import json
import sys
import tempfile
from pathlib import Path
import numpy as np
import cv2
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.crossing import crossing_occupancy, apply_crossing_guard
from app.gap_forecast import GapForecast
from app.motion import MotionEngine
from app.risk import RiskEngine
from app.safe_window import SafeWindowPredictor
from app.learning import OnlineLearner
cfg = json.loads((ROOT/'config.json').read_text())
r = RiskEngine(cfg['risk'])
chicken = dict(cx=190., cy=731., h=160.)

# Signal 40's logged box: upper corridor can be empty while tail overlaps
# buffered crossing. This is a reconstructed mask, not the original video.
mask = np.zeros((1600,2560), np.uint8)
mask[769:835,562:756] = 255
assert r._incoming_motion_corridor(mask,651.,731.)['clear']
c = crossing_occupancy(mask,651.,chicken,r)
assert c['crossing_motion_available'] and not c['crossing_motion_clear'], c
assert not apply_crossing_guard(dict(c,green_evidence_ok=True))['green_evidence_ok']
with tempfile.TemporaryDirectory() as td:
    p = SafeWindowPredictor(Path(td),cfg['safe_window_v5'])
    state = dict(c,processing_healthy=True,target_green_geometry_ok=True,motion_ready=True)
    assert p._hard_veto(state) == (False,'CROSSING OCCUPIED')
    p.n = max(100,p.min_samples)
    p._predict = lambda s,x:(.999,'test')
    p._commit_active = True
    p._verified_hold_until = 20.
    p._commit_started = 9.9
    state.update(lane=1,raw_risk=2.,risk=2.,effective_eta=3.)
    out = p.apply(state,now=10.)
    assert not out['v5_decision'] and out['v5_hard_reason']=='CROSSING OCCUPIED'
# Passed car, far upstream car, and adjacent lane never create this veto.
for box in [(950,1010,562,756),(100,180,562,756),(769,835,1000,1200)]:
    m = np.zeros_like(mask);a,b,x,y = box;m[a:b,x:y]=255
    assert crossing_occupancy(m,651.,chicken,r)['crossing_motion_clear']
# Cropped masks use global coordinates and must cover the entire strip.
cropped=dict(mask=mask[50:877,378:924],x0=378,y0=50,ready=True)
assert not crossing_occupancy(cropped,651.,chicken,r)['crossing_motion_clear']
cropped['mask']=cropped['mask'][:700]
assert not crossing_occupancy(cropped,651.,chicken,r)['crossing_motion_available']

# A mode change within one open gap cannot expand its bound or reduce budget.
f = GapForecast()
assert f.update((1,7),True,1.8258,1.4274)==(1.8258,1.4274)
assert f.update((1,7),True,2.0770,1.3814)==(1.8258,1.4274)
f.update((1,7),False,2.0770,1.3814)
assert f.update((1,7),True,2.0770,1.3814)==(1.8258,1.4274)
assert f.update((1,7),True,1.7,1.45)==(1.7,1.45)
assert f.update((1,8),True,2.077,1.38)==(2.077,1.38)
f.reset();assert f.update((1,8),True,3.,1.2)==(3.,1.2)

# A full-size car accepted at 1280 must not disappear at 2560 solely because
# its contour area quadrupled. Real MotionEngine + MOG/diff/morphology path.
def detect(width, legacy=False):
    e = MotionEngine(cfg['tracking'])
    if legacy:e.blob_reference_width=1e9
    scale=width/1280.
    frame=np.zeros((int(800*scale),width,3),np.uint8)
    roi=tuple(int(z*scale) for z in (175,25,450,440))
    for _ in range(7):e._detections(frame,roi)
    cv2.rectangle(frame,(int(240*scale),int(100*scale)),
                  (int(390*scale),int(220*scale)),(255,255,255),-1)
    return e._detections(frame,roi)
assert detect(1280)
assert not detect(2560,legacy=True)
assert detect(2560)

# CSV telemetry stays aligned after the new fields are appended.
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
    l.log_state(dict(c,dynamic_gap_unlatched_lower_bound=2.077),None,[])
    l.flush(save_model=False)
    path=next(l.folder.glob('state_*.csv'))
    rows=list(csv.reader(path.open()))
    assert len(rows[0])==len(rows[1]),(len(rows[0]),len(rows[1]))
    assert 'crossing_motion_ratio' in rows[0]

# Optional recorded-state check: no future physical accuracy claim is implied.
if len(sys.argv)>1:
    rows=list(csv.DictReader(Path(sys.argv[1]).open()))
    f=GapForecast();n=0
    for row in rows:
        if row['dynamic_gap_cycle_id']!='877' or row['motion_corridor_clear']!='1':continue
        b,q=f.update((1,877),True,float(row['dynamic_gap_lower_bound']),
                     float(row['dynamic_gap_required_eta']))
        if row['green_confirmed']=='1':
            remaining=b-float(row['dynamic_gap_effective_clear_elapsed'])
            assert remaining < q,(remaining,q)
            n+=1
    assert n
    print('PASS recorded signal 40: same-gap mode easing no longer supplies claimed headroom')
print('PASS V5511 crossing strip, hard veto, crop coverage, valid clear cases, forecast episodes, scaled real detector, CSV schema')
