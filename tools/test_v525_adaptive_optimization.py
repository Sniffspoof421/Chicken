from pathlib import Path
import tempfile
from app.safe_window import SafeWindowPredictor


def base_state():
    return {
        'stage_difficulty_score':0.10,
        'live_speed_difficulty_score':0.0,
        'motion_gap_support':20,
        'processing_healthy':True,
        'recent_green_reliability':0.8,
        'recent_green_failures':0,
        'recent_green_successes':0,
        'effective_eta':1.35,
        'lane':'1',
        'chicken_fresh':True,
        'target_lane_switches':0,
        'viewport_rebase_count':0,
        'dynamic_gap_cycle_id':1,
        'green_evidence_ok':False,
        'green_evidence_reason':'',
    }

with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),{
        'min_training_samples':0,
        'easy_probability_threshold':.91,
        'hard_probability_threshold':.88,
        'adaptive_probability_floor':.885,
        'green_commit_dwell_seconds':.40,
        'green_commit_hard_add_seconds':-.04,
        'green_commit_min_seconds':.36,
        'green_commit_max_seconds':.42,
        'green_precommit_dropout_grace_seconds':.14,
        'green_precommit_exit_probability_margin':.025,
        'min_live_gap_support':8,
    })
    easy=base_state()
    hard=base_state(); hard['live_speed_difficulty_score']=.90
    te=p._threshold(easy); th=p._threshold(hard)
    assert abs(te-.91)<1e-6, (te,th)
    assert .885 <= th < .91, (te,th)

    # Controlled pre-commit sequence: a tiny soft probability dip must not
    # erase the sustained candidate, but a hard veto still must.
    p._hard_veto=lambda s:(not s.get('test_hard',False), 'TEST' if s.get('test_hard',False) else '')
    p._predict=lambda s,x:(float(s['test_prob']),'test')
    p._maybe_add_candidate=lambda *args,**kwargs:None
    p._update_pending=lambda *args,**kwargs:''
    p.n=100
    s=base_state(); s['test_prob']=.92
    out=p.apply(dict(s),now=10.00); assert not out['v5_decision']
    s['test_prob']=.895  # below .91, but within .025 soft margin
    out=p.apply(dict(s),now=10.10); assert not out['v5_decision']
    s['test_prob']=.92
    out=p.apply(dict(s),now=10.39); assert not out['v5_decision']
    out=p.apply(dict(s),now=10.41); assert out['v5_decision'], out
    s['test_hard']=True
    out=p.apply(dict(s),now=10.42); assert not out['v5_decision']

print('PASS v525 adaptive threshold + precommit grace')
