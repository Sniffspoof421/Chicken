import json, tempfile, sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.safe_window import SafeWindowPredictor

class IdentityScaler:
    def transform(self, X): return np.asarray(X,dtype=float)
class FixedModel:
    def __init__(self,p): self.p=float(p)
    def predict_proba(self,X):
        return np.asarray([[1.0-self.p,self.p] for _ in X],dtype=float)

cfg=json.load(open(ROOT/'config.json'))['safe_window_v5']
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    p=SafeWindowPredictor(r,cfg)
    p.fitted=True; p.n=58000
    p.scaler=IdentityScaler(); p.model=FixedModel(.28)
    p._heuristic_probability=lambda s,x:.92
    x=np.zeros(len(p.FEATURE_NAMES),dtype=float)
    q,mode=p._predict({},x)
    assert mode=='longterm-prior', (q,mode)
    assert abs(q-(.60*.92+.40*.28)) < 1e-9, q
    # Current-session evidence must become dominant after support matures.
    p.session_fitted=True; p.session_n=90
    p.session_scaler=IdentityScaler(); p.session_model=FixedModel(.90)
    q2,mode2=p._predict({},x)
    assert mode2=='session-adaptive', (q2,mode2)
    assert q2 > .80, q2

    base={
        'stage_difficulty_score':.76,'live_speed_difficulty_score':.8,
        'motion_gap_support':20,'motion_gap_p25':1.40,'czn_confirmed_events':0,
        'motion_current_clear_elapsed':1.4,'effective_eta':1.10,
        'motion_corridor_ratio':0.0,'dynamic_gap_mog_global_ratio':0.0,
        'raw_risk':2.0,'processing_healthy':True,
    }
    assert not p._observed_clear_physical_ready(base,1.08,.70), 'weak no-CZN gap must not override'
    strong=dict(base); strong['motion_gap_p25']=1.80
    assert p._observed_clear_physical_ready(strong,1.08,.70), 'strong P25 gap should override'
    current=dict(base); current['czn_confirmed_events']=3
    assert p._observed_clear_physical_ready(current,1.08,.70), 'current CZN proof should override'
    p._log_file.close()
print('PASS v532 two-timescale learning + evidence-qualified observed-clear override')
