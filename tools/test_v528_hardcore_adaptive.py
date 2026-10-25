from pathlib import Path
import tempfile
from app.safe_window import SafeWindowPredictor


def state():
    return {
        'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
        'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
        'motion_ready':True,'visible_threat':False,'uncertain_incoming_count':0,
        'lane_visibility_ok':True,'lane_visibility_score':.95,
        'motion_corridor_ratio':.01,'motion_clear_dwell':1.0,
        'motion_current_clear_elapsed':1.0,'dynamic_gap_mog_global_ratio':.01,
        'raw_risk':2.0,'crash_memory_score':0.0,'crash_memory_matches':0,
        'dynamic_gap_slow_guard':0,'effective_eta':1.25,
        'stage_difficulty_score':.20,'live_speed_difficulty_score':1.0,
        'live_density_difficulty_score':.5,'stage_gap_p25':.90,
        'motion_gap_support':30,'motion_gap_p25':1.30,
        'motion_live_ready':True,'czn_live_ready':True,
        'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.5,
        'active_tracks':0,'dynamic_gap_ready':False,'gap_open_ready':False,
        'eta_source_reliability':.8,'adaptive_confidence':.85,
        'dynamic_gap_confidence':.8,'recent_green_reliability':.8,
        'recent_green_failures':0,'recent_green_successes':0,'clear_dwell':1.0,
        'lane':'1','chicken_fresh':True,'target_lane_switches':0,
        'viewport_rebase_count':0,'dynamic_gap_cycle_id':1,
        'green_evidence_ok':False,'green_evidence_reason':'',
        'slow_window_reason':'NO VERIFIED SLOW WINDOW',
        'slow_window_profile_support':20,'slow_window_profile_confidence':.9,
        'slow_window_p25_gap':1.5,
    }

cfg={
    'enabled':True,'min_training_samples':0,'save_interval_seconds':99999,
    'absolute_min_eta_seconds':1.08,'verified_gap_min_eta_seconds':1.08,
    'observed_clear_min_eta_seconds':1.08,'forecast_min_eta_seconds':1.12,
    'min_live_gap_p25_seconds':.95,'min_live_gap_support':8,
    'min_preceding_busy_seconds':.16,'min_motion_clear_dwell_seconds':.3,
    'observed_clear_min_elapsed_seconds':.7,'observed_clear_min_gap_p25_seconds':1.1,
    'historical_slow_after_current_gap_floor_seconds':1.25,
    'historical_slow_after_risk_trigger':.3,
    'base_probability_threshold':.90,'easy_probability_threshold':.91,
    'hard_probability_threshold':.88,'adaptive_probability_floor':.885,
    'verified_gap_probability_floor_easy':.82,'verified_gap_probability_floor_hard':.74,
    'observed_clear_probability_floor_easy':.85,'observed_clear_probability_floor_hard':.79,
    'tracked_forecast_probability_floor_easy':.90,'tracked_forecast_probability_floor_hard':.86,
    'slow_before_probability_floor_easy':.84,'slow_before_probability_floor_hard':.78,
    'physical_slow_risk_probability_penalty':.015,
    'gap_difficulty_easy_seconds':1.55,'gap_difficulty_hard_seconds':.80,
    'speed_difficulty_weight':.72,'gap_difficulty_weight':.88,'density_difficulty_weight':.55,
    'green_commit_dwell_seconds':.32,'green_commit_hard_add_seconds':-.04,
    'green_commit_min_seconds':.28,'green_commit_max_seconds':.34,
    'green_precommit_dropout_grace_seconds':.16,'green_precommit_exit_probability_margin':.025,
}

with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),cfg)
    p.n=100
    p._maybe_add_candidate=lambda *a,**k:None
    p._update_pending=lambda *a,**k:''
    p._predict=lambda s,x:(float(s.get('test_prob',.82)),'test')

    # Hardcore: compressed gap + high speed lowers only the final physical
    # confidence floor. All hard safety checks still have to pass.
    a=state(); a['test_prob']=.82
    o=p.apply(dict(a),10.0)
    assert o['v5_gap_provenance']=='observed-clear', o
    assert o['v5_effective_difficulty'] >= .70, o['v5_effective_difficulty']
    assert o['v5_admission_threshold'] < o['v5_safe_threshold'], o
    assert o['v5_raw_decision'] and o['v5_physical_override'], o
    req=o['v5_commit_required']
    p.apply(dict(a),10.15)
    o=p.apply(dict(a),10.15+req)
    assert o['v5_decision'], (req,o)

    # Easy/long-gap scene should not get the same hardcore relaxation.
    b=state(); b.update({'stage_difficulty_score':.05,'live_speed_difficulty_score':.05,
                         'live_density_difficulty_score':0.0,'stage_gap_p25':1.50,
                         'test_prob':.82,'dynamic_gap_cycle_id':2})
    p._commit_key=None; p._commit_since=None; p._commit_last_good=None; p._commit_active=False
    o=p.apply(dict(b),20.0)
    assert o['v5_admission_threshold'] > .83, o
    assert not o['v5_raw_decision'], o

    # Strong verified gap can use a lower sanity floor, but ETA hard floor stays.
    c=state(); c.update({'dynamic_gap_ready':True,'test_prob':.77,'dynamic_gap_cycle_id':3})
    p._commit_key=None; p._commit_since=None; p._commit_last_good=None; p._commit_active=False
    o=p.apply(dict(c),30.0)
    assert o['v5_gap_provenance']=='verified-gap', o
    assert o['v5_raw_decision'], o
    d=dict(c); d['effective_eta']=1.04; d['dynamic_gap_cycle_id']=4
    p._commit_key=None; p._commit_since=None; p._commit_last_good=None; p._commit_active=False
    o=p.apply(d,31.0)
    assert not o['v5_raw_decision'] and o['v5_hard_reason']=='PHYSICAL ETA', o

    # Blind/unverified empty ROI remains blocked regardless of ML probability.
    e=state(); e.update({'motion_live_ready':False,'dynamic_gap_preceding_busy_ok':False,
                         'test_prob':.99,'dynamic_gap_cycle_id':5})
    p._commit_key=None; p._commit_since=None; p._commit_last_good=None; p._commit_active=False
    o=p.apply(e,40.0)
    assert not o['v5_raw_decision'] and o['v5_hard_reason']=='LIVE GAP UNVERIFIED', o
    p._log_file.close()

print('PASS v528 hardcore adaptive hybrid admission')
