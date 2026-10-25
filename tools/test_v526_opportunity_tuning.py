from pathlib import Path
import json, tempfile
from app.safe_window import SafeWindowPredictor

root=Path(__file__).resolve().parents[1]
cfg=json.loads((root/'config.json').read_text())['safe_window_v5']
assert cfg['green_commit_min_seconds']==0.28
assert cfg['green_commit_max_seconds']==0.34
assert cfg['green_commit_dwell_seconds']==0.32

state={
 'stage_difficulty_score':.30,'live_speed_difficulty_score':.30,
 'motion_gap_support':20,'processing_healthy':True,
 'recent_green_reliability':.8,'recent_green_failures':0,'recent_green_successes':0,
 'effective_eta':1.40,'lane':'1','chicken_fresh':True,'target_lane_switches':0,
 'viewport_rebase_count':0,'dynamic_gap_cycle_id':1,
 'green_evidence_ok':False,'green_evidence_reason':'','test_prob':.95,
}
with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),cfg)
    p._hard_veto=lambda s:(not s.get('test_hard',False), 'TEST' if s.get('test_hard',False) else '')
    p._predict=lambda s,x:(float(s['test_prob']),'test')
    p._maybe_add_candidate=lambda *a,**k:None
    p._update_pending=lambda *a,**k:''
    p.n=max(100,p.min_samples)
    o=p.apply(dict(state),now=10.00)
    req=o['v5_commit_required']
    assert .28 <= req <= .34, req
    o=p.apply(dict(state),now=10.24)
    assert not o['v5_decision'], o
    o=p.apply(dict(state),now=10.32)
    assert o['v5_decision'], (req,o)
    h=dict(state); h['test_hard']=True
    o=p.apply(h,now=10.33)
    assert not o['v5_decision']
print('PASS v526 opportunity tuning')
