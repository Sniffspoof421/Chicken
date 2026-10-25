import tempfile, joblib
from pathlib import Path
from app.learning import OnlineLearner
from app.safe_window import SafeWindowPredictor

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    (root/'data/sessions').mkdir(parents=True)
    (root/'data/models').mkdir(parents=True)
    joblib.dump({
        'pattern_event_n':321,
        'event_speeds':[80.,110.,150.],
        'crash_memory':[{'timestamp':1.0,'weight':1.0,'source':'crash','context':{'x':1}}],
        'safe_memory':[{'timestamp':1.0,'weight':1.0,'source':'old','context':{'x':1}}],
        'green_failure_n':4,
        'green_source_action_delays':{'v5-safe-window':[1.4,1.6]},
    }, root/'data/models/online_state_v520.joblib')
    l=OnlineLearner(root/'data/sessions',{})
    assert l.state_path.name=='online_state_v522.joblib'
    assert l.pattern_event_n==321, l.pattern_event_n
    assert len(l.crash_memory)==1
    # Migration intentionally drops stale SAFE/outcome labels while keeping
    # traffic/crash history; V5.2.2 relearns GREEN outcomes correctly.
    assert len(l.safe_memory)==0
    assert l.green_failure_n==0
    assert len(l.green_source_action_delays['v5-safe-window'])==0

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    p=SafeWindowPredictor(root,{'enabled':True,'min_training_samples':10})
    assert p.model_path.name=='safe_window_v522.joblib'
    assert p.legacy_model_path.name=='safe_window_v521.joblib'
    p._log_file.close()

print('PASS v5.2.2 migration preserves traffic/crash history and resets polluted outcome timing')
