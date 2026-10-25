import tempfile, joblib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.learning import OnlineLearner
from app.safe_window import SafeWindowPredictor

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    (root/'data/sessions').mkdir(parents=True)
    (root/'data/models').mkdir(parents=True)
    joblib.dump({
        'pattern_event_n':321,
        'safe_memory':[{'timestamp':1.0,'weight':1.0,'source':'v529','context':{'x':1}}],
        'green_failure_n':4,
        'green_success_n':5,
        'green_source_failures':{'v5-safe-window':4},
        'green_source_successes':{'v5-safe-window':5},
    }, root/'data/models/online_state_v529.joblib')
    l=OnlineLearner(root/'data/sessions',{})
    assert l.state_path.name=='online_state_v530.joblib'
    assert l.pattern_event_n==321
    assert len(l.safe_memory)==1
    assert l.green_failure_n==4
    assert l.green_success_n==5

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    (root/'data/sessions').mkdir(parents=True)
    (root/'data/models').mkdir(parents=True)
    p=SafeWindowPredictor(root,{'enabled':True,'min_training_samples':10})
    assert p.model_path.name=='safe_window_v530.joblib'
    assert p.legacy_model_paths[0].name=='safe_window_v529.joblib'
    p._log_file.close()

print('PASS v530 migration preserves v529 learning paths')
