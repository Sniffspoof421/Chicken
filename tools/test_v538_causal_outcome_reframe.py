import json, tempfile, sys, joblib
from pathlib import Path
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.outcome import GreenJumpOutcomeTracker
from app.scene_motion import FullscreenProgressReframeGate
from app.learning import OnlineLearner
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())

# 1) No observed action => later crash can NEVER fabricate a GREEN failure.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.pending_signal={
    'signal_id':71,'start_ts':10.0,'end_ts':10.6,'duration':0.6,
    'baseline_x':630.0,'lane':2,'eta_source':'v5-safe-window','eta':1.7,
    'expected_jump_px':440.0,
}
e=o.on_crash({
    'event_time':13.0,'reason':'confirmed_progress_reset',
    'start_x':190.0,'max_x':1070.0,'reset_x':190.0,'progress_px':880.0
},13.0)
assert e is None, e
assert o.failures==0 and o.acted_signals==0, o.status()
assert o.crash_fallback_ignored==1, o.status()

# 2) More than one jump is CHAINED/UNVALIDATED before regression can call failure.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.active_attempt={
    'signal_id':72,'baseline_x':190.0,'action_start_x':220.0,
    'action_start_ts':20.0,'expected_jump_px':440.0,
    'last_x':1070.0,'max_x':1070.0,'stable_since':None,
}
ev=o._attempt_progress({'cx':190.0},21.0)
assert len(ev)==1 and ev[0]['outcome']=='chained_unvalidated',ev
assert o.failures==0 and o.chained==1, o.status()

# 3) Crash arriving before outcome polling also respects one-jump ownership.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.active_attempt={
    'signal_id':73,'baseline_x':190.0,'action_start_x':220.0,
    'action_start_ts':30.0,'expected_jump_px':440.0,
    'last_x':630.0,'max_x':630.0,'stable_since':None,
}
ev=o.on_crash({
    'event_time':31.0,'reason':'confirmed_progress_reset',
    'start_x':190.0,'max_x':1070.0,'reset_x':190.0,'progress_px':880.0
},31.0)
assert ev and ev['outcome']=='chained_unvalidated',ev
assert o.failures==0 and o.chained==1, o.status()

# 4) A true one-jump crash remains learnable.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.active_attempt={
    'signal_id':74,'baseline_x':190.0,'action_start_x':220.0,
    'action_start_ts':40.0,'expected_jump_px':440.0,
    'last_x':600.0,'max_x':630.0,'stable_since':None,
    'attribution':'green_active','attribution_confidence':1.0,
}
ev=o.on_crash({
    'event_time':40.8,'reason':'confirmed_progress_reset',
    'start_x':190.0,'max_x':630.0,'reset_x':190.0,'progress_px':440.0
},40.8)
assert ev and ev['outcome']=='failure' and ev['one_jump_valid'] is True,ev
assert o.failures==1,o.status()

# 5) Split low-FPS fullscreen cut: 1070 -> 700 -> 190 must still be progress.
g=FullscreenProgressReframeGate(cfg['tracking'])
assert not g.update({'cx':190},440,2560,0.0)['detected']
assert not g.update({'cx':630},440,2560,0.5)['detected']
assert not g.update({'cx':1070},440,2560,1.0)['detected']
assert not g.update({'cx':700},440,2560,1.30)['detected']
cut=g.update({'cx':190},440,2560,1.60)
assert cut['detected'],cut
assert cut['source']=='recent_peak',cut
assert 1.9 <= cut['shift_lanes'] <= 2.1,cut

# One-lane death is still not a reframe.
g=FullscreenProgressReframeGate(cfg['tracking'])
g.update({'cx':190},440,2560,0.0)
g.update({'cx':630},440,2560,0.6)
one=g.update({'cx':190},440,2560,1.2)
assert not one['detected'],one

# 6) Crash geometry secondary safety net recognizes missed two-lane game cut.
g=FullscreenProgressReframeGate(cfg['tracking'])
ce=g.classify_crash_event({
    'max_x':1070.0,'reset_x':190.0,'start_x':190.0,'progress_px':880.0
},440,2560,5.0)
assert ce['detected'] and ce['source']=='crash_geometry',ce
assert 1.9 <= ce['shift_lanes'] <= 2.1,ce

# 7) Policy 536/537 failure-only memory is cleaned once under policy 538.
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/sessions').mkdir(parents=True); (r/'data/models').mkdir(parents=True)
    joblib.dump({
        'green_failure_n':6,'green_success_n':4,
        'green_pattern_failures':{'X':6},
        'green_source_failures':{'v5-safe-window':6},
        'green_source_successes':{'v5-safe-window':4},
        'green_source_failure_etas':{'v5-safe-window':[1.2,1.3]},
        'green_source_action_delays':{'v5-safe-window':[0.3]},
        'green_speed_failures':{'F':6},
        'green_speed_successes':{'S':4},
        'pattern_event_n':321,
        'green_attribution_policy_version':536,
    },r/'data/models/online_state_v532.joblib')
    l=OnlineLearner(r/'data/sessions',{})
    assert l.green_failure_n==0
    assert l.green_success_n==4
    assert not l.green_source_failures and not l.green_source_failure_etas
    assert l.green_source_successes['v5-safe-window']==4
    assert l.pattern_event_n==321

with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/sessions').mkdir(parents=True); (r/'data/models').mkdir(parents=True)
    vec=[0.0]*len(SafeWindowPredictor.FEATURE_NAMES)
    joblib.dump({
        'scaler':StandardScaler(),'model':SGDClassifier(loss='log_loss'),'fitted':False,
        'n':500,'safe_n':260,'unsafe_n':240,
        'feature_names':tuple(SafeWindowPredictor.FEATURE_NAMES),
        'failure_feedback':[{'x':vec,'weight':1.0}],
        'feedback_failures':6,'feedback_successes':4,
        'feedback_policy_version':536,
    },r/'data/models/safe_window_v532.joblib')
    p=SafeWindowPredictor(r,{'enabled':True,'min_training_samples':60})
    assert p.n==500 and p.feedback_failures==0 and len(p.failure_feedback)==0
    assert p.feedback_successes==4
    p._log_file.close()

print('PASS V5.3.8 causal GREEN attribution + one-jump ownership + recent-peak reframe + migration')
