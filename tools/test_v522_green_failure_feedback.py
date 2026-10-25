import tempfile, time
from pathlib import Path

from app.safe_window import SafeWindowPredictor
from app.learning import OnlineLearner


def base_state():
    return {
        'lane': 2,
        'processing_healthy': True,
        'sensor_desync': False,
        'tracking_rewarm': False,
        'viewport_hold': False,
        'vision_hold': False,
        'target_green_geometry_ok': True,
        'motion_ready': True,
        'active_tracks': 0,
        'dynamic_gap_ready': True,
        'gap_open_ready': False,
        'motion_live_ready': True,
        'czn_live_ready': True,
        'dynamic_gap_preceding_busy_ok': True,
        'motion_preceding_busy_duration': .5,
        'motion_gap_support': 30,
        'motion_gap_p25': 1.8,
        'visible_threat': False,
        'uncertain_incoming_count': 0,
        'lane_visibility_ok': True,
        'lane_visibility_score': .92,
        'motion_corridor_ratio': .01,
        'motion_clear_dwell': .7,
        'dynamic_gap_mog_global_ratio': .01,
        'raw_risk': 4.0,
        'effective_eta': 1.55,
        'crash_memory_score': 0.0,
        'crash_memory_matches': 0,
        'dynamic_gap_slow_guard': 0,
        'stage_difficulty_score': .55,
        'eta_source_reliability': .8,
        'adaptive_confidence': .85,
        'dynamic_gap_confidence': .9,
        'recent_green_reliability': .8,
        'clear_dwell': .8,
        'slow_window_mode': '',
        'processing_fps': 6.0,
        'chicken_fresh': True,
        'target_lane_switches': 0,
        'viewport_rebase_count': 0,
        'manual_failures': 0,
        'crashes_learned': 0,
        'green_failures_learned': 0,
        'dynamic_gap_cycle_id': 77,
        'green_evidence_ok': True,
        'green_evidence_reason': '',
    }

with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    cfg={
        'enabled':True,
        'min_training_samples':0,
        'failure_memory_hard_similarity':.93,
        'failure_memory_probability_penalty':.18,
        'save_interval_seconds':9999,
    }
    p=SafeWindowPredictor(root,cfg)
    s=base_state()
    x=p._features(s)
    evt={
        'outcome':'failure', 'signal_id':9,
        'outcome_ts':time.time(), 'attribution_confidence':.8,
        'post_green_delay':.7, 'v5_feature_vector':x.tolist(),
    }
    assert p.record_green_feedback(evt)==1
    assert p.feedback_failures==1
    assert p.unsafe_n==1
    sim=p._failure_similarity(x,time.time())
    assert sim >= .93, sim
    s2=base_state()
    out=p.apply(s2,time.time()+.1)
    assert not out['v5_decision'], out
    assert out['v5_hard_reason']=='LEARNED GREEN FAILURE', out['v5_hard_reason']
    p._log_file.close()

with tempfile.TemporaryDirectory() as td:
    folder=Path(td)/'sessions'
    cfg={
        'late_green_causal_max_seconds':2.2,
        'outcome_failure_weight':5.0,
        'outcome_success_weight':4.0,
        'balanced_ml_min_per_class':3,
    }
    l=OnlineLearner(folder,cfg)
    evt={
        'outcome':'failure', 'signal_id':2,
        'start_ts':100.0, 'end_ts':100.5,
        'action_start_ts':101.4,
        'post_green_delay':.9,
        'attribution':'post_green_grace',
        'attribution_confidence':.75,
        'outcome_ts':102.0,
        'eta_source':'v5-safe-window', 'lane':2,
        'eta':1.35, 'speed_pattern':'-', 'type_pattern':'-',
        'features':None, 'safety_context':None,
    }
    used=l.record_green_outcome(evt)
    assert used==1, 'causal late GREEN failure must be training eligible'
    assert l.green_source_failures['v5-safe-window']==1
    assert l.green_source_late_failures['v5-safe-window']==1
    # Failed/purposeful crashes must not teach a slow user reaction budget.
    assert len(l.green_source_action_delays['v5-safe-window'])==0

print('PASS v5.2.2 direct GREEN failure feedback + causal late learning')
