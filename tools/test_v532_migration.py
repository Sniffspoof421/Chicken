import tempfile, joblib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.learning import OnlineLearner
from app.safe_window import SafeWindowPredictor
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/sessions').mkdir(parents=True); (root/'data/models').mkdir(parents=True)
    joblib.dump({
        'pattern_event_n':531,'safe_memory':[{'timestamp':1.0,'weight':1.0,'source':'v531','context':{'x':1}}],
        'green_failure_n':6,'green_success_n':6,
        'green_source_failures':{'v5-safe-window':6},'green_source_successes':{'v5-safe-window':6},
    }, root/'data/models/online_state_v531.joblib')
    l=OnlineLearner(root/'data/sessions',{})
    assert l.state_path.name=='online_state_v532.joblib'
    assert l.pattern_event_n==531 and len(l.safe_memory)==1
    assert l.green_failure_n==6 and l.green_success_n==6

with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/sessions').mkdir(parents=True); (root/'data/models').mkdir(parents=True)
    joblib.dump({
        'scaler':StandardScaler(),'model':SGDClassifier(loss='log_loss'), 'fitted':False,
        'n':58162,'safe_n':27463,'unsafe_n':30699,
        'feature_names':tuple(SafeWindowPredictor.FEATURE_NAMES), 'model_version':'v531',
        'failure_feedback':[], 'feedback_failures':5,'feedback_successes':5,
    }, root/'data/models/safe_window_v531.joblib')
    p=SafeWindowPredictor(root,{'enabled':True,'min_training_samples':60})
    assert p.model_path.name=='safe_window_v532.joblib'
    assert p.legacy_model_paths[0].name=='safe_window_v531.joblib'
    assert p.n==58162 and p.safe_n==27463 and p.unsafe_n==30699
    assert p.session_n==0 and not p.session_fitted
    p._log_file.close()
print('PASS v532 migration preserves v531 long-term model and starts fresh session learner')
