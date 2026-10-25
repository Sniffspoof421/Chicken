import tempfile, joblib, sys
from pathlib import Path
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.learning import OnlineLearner
from app.safe_window import SafeWindowPredictor

with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/sessions').mkdir(parents=True); (root/'data/models').mkdir(parents=True)
    joblib.dump({
        'green_failure_n':11,'green_success_n':8,
        'green_pattern_failures':{'A':5},
        'green_source_failures':{'v5-safe-window':11},
        'green_source_successes':{'v5-safe-window':8},
        'green_source_failure_etas':{'v5-safe-window':[1.1,1.2]},
        'green_source_action_delays':{'v5-safe-window':[0.3,0.4]},
        'green_speed_failures':{'F':4},
        'green_speed_successes':{'S':3},
        'pattern_event_n':123,
        # no green_attribution_policy_version => pre-v536 contaminated policy
    }, root/'data/models/online_state_v532.joblib')
    l=OnlineLearner(root/'data/sessions',{})
    assert l.green_failure_n==0
    assert l.green_success_n==8
    assert not l.green_pattern_failures and not l.green_source_failures
    assert not l.green_source_failure_etas and not l.green_speed_failures
    assert l.green_source_successes['v5-safe-window']==8
    assert l.pattern_event_n==123

with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/sessions').mkdir(parents=True); (root/'data/models').mkdir(parents=True)
    vec=[0.0]*len(SafeWindowPredictor.FEATURE_NAMES)
    joblib.dump({
        'scaler':StandardScaler(),'model':SGDClassifier(loss='log_loss'),'fitted':False,
        'n':500,'safe_n':250,'unsafe_n':250,
        'feature_names':tuple(SafeWindowPredictor.FEATURE_NAMES),
        'failure_feedback':[{'x':vec,'weight':3.0}],
        'feedback_failures':9,'feedback_successes':7,
        # no feedback_policy_version => pre-v536
    }, root/'data/models/safe_window_v532.joblib')
    p=SafeWindowPredictor(root,{'enabled':True,'min_training_samples':60})
    assert p.n==500 and p.safe_n==250 and p.unsafe_n==250
    assert p.feedback_failures==0 and len(p.failure_feedback)==0
    assert p.feedback_successes==7
    p._log_file.close()
print('PASS V5.3.6 policy migration clears contaminated GREEN-failure memory and preserves long-term/success learning')
