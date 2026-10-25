import tempfile
from pathlib import Path
from app.safe_window import SafeWindowPredictor


def make_state():
    return {
        'lane':'1','target_lane_switches':1,'viewport_rebase_count':0,
        'stage_difficulty_score':0.5,'effective_eta':1.50,
        'green_evidence_ok':False,'green_evidence_reason':'',
    }

with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),{
        'min_training_samples':1,
        'green_commit_dwell_seconds':0.40,
        'green_commit_hard_add_seconds':0.0,
        'green_commit_dropout_grace_seconds':0.42,
        'green_commit_exit_probability_margin':0.035,
        'green_commit_exit_eta_margin_seconds':0.06,
        'save_interval_seconds':999999,
    })
    p.n=100
    p._features=lambda s: __import__('numpy').zeros(len(p.FEATURE_NAMES))
    p._update_pending=lambda now,s: ''
    p._maybe_add_candidate=lambda *args,**kwargs: None
    p._threshold=lambda s: 0.90
    current={'prob':0.94,'hard':True}
    p._predict=lambda s,x: (current['prob'],'test')
    p._hard_veto=lambda s: (current['hard'],'') if current['hard'] else (False,'VISIBLE THREAT')

    s=make_state()
    # A transient/flicker pulse must never display GREEN.
    a=p.apply(dict(s),1.00); assert not a['v5_decision']
    a=p.apply(dict(s),1.18); assert not a['v5_decision']
    current['prob']=0.80
    a=p.apply(dict(s),1.28); assert not a['v5_decision']

    # A sustained candidate must mature before GREEN.
    current['prob']=0.94
    a=p.apply(dict(s),2.00); assert not a['v5_decision']
    a=p.apply(dict(s),2.20); assert not a['v5_decision']
    a=p.apply(dict(s),2.41); assert a['v5_decision'] and a['v5_committed']

    # Small probability jitter is tolerated once committed.
    current['prob']=0.885  # below 0.90, above 0.865 exit boundary
    a=p.apply(dict(s),2.55); assert a['v5_decision']

    # A hard hazard still kills GREEN immediately.
    current['hard']=False
    a=p.apply(dict(s),2.60); assert not a['v5_decision']

    # A lane/target change must require a new commit dwell.
    current['hard']=True; current['prob']=0.95
    s2=make_state(); s2['target_lane_switches']=2
    a=p.apply(dict(s2),3.00); assert not a['v5_decision']

print('PASS v523 sustained GREEN commit')
