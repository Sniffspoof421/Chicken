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
        'safe_memory':[{'timestamp':1.0,'weight':1.0,'source':'v523','context':{'x':1}}],
        'green_failure_n':4,
        'green_success_n':2,
        'green_source_failures':{'v5-safe-window':4},
        'green_source_successes':{'v5-safe-window':2},
    }, root/'data/models/online_state_v523.joblib')
    l=OnlineLearner(root/'data/sessions',{})
    assert l.state_path.name=='online_state_v524.joblib'
    assert l.pattern_event_n==321
    assert len(l.safe_memory)==1
    assert l.green_failure_n==4
    assert l.green_success_n==2
    assert l.green_source_failures['v5-safe-window']==4

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    (root/'data/sessions').mkdir(parents=True)
    (root/'data/models').mkdir(parents=True)
    # Creating predictor with no legacy file still verifies path preference.
    p=SafeWindowPredictor(root,{'enabled':True,'min_training_samples':10})
    assert p.model_path.name=='safe_window_v524.joblib'
    assert p.legacy_model_path.name=='safe_window_v523.joblib'
    p._log_file.close()

print('PASS v524 migration paths preserve v523 learning')
