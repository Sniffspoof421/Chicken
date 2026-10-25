from pathlib import Path
import tempfile
from app.outcome import GreenJumpOutcomeTracker
from app.safe_window import SafeWindowPredictor

# 1) Only a confirmed visible CLEAR becomes an outcome-owned GREEN.
o=GreenJumpOutcomeTracker({'post_green_action_grace_seconds':2.1,'outcome_timeout_seconds':5.5})
base={'indicator_state':'CLEAR','green_confirmed':False,'lane':1,'eta_source':'v5-safe-window',
      'effective_eta':1.4,'raw_risk':2,'display_risk':2,'scene_pan_active':False,'chicken_fresh':True}
o.update(dict(base),{'cx':100.0},1.0)
assert o.green_signals==0, o.status()
base['green_confirmed']=True
o.update(dict(base),{'cx':100.0},1.1)
assert o.green_signals==1, o.status()

# 2) Acted GREEN survives viewport/camera rebasing and can still learn failure.
ev=o.update(dict(base),{'cx':125.0},1.3)
assert any(x.get('kind')=='action_started' for x in ev), ev
assert o.active_attempt is not None
sid=o.active_attempt['signal_id']
b0=o.active_attempt['baseline_x']
o.rebase_viewport(-40.0)
assert o.active_attempt is not None and o.active_attempt['signal_id']==sid
assert abs(o.active_attempt['baseline_x']-(b0-40.0))<1e-9
o.invalidate_unacted_viewport({'cx':85.0})
assert o.active_attempt is not None, 'acted GREEN must not be cancelled by viewport invalidation'
f=o.on_crash({'event_time':2.0,'reason':'confirmed_progress_reset','start_x':85.0,'max_x':260.0,'reset_x':85.0},2.0)
assert f is not None and f['outcome']=='failure' and f['signal_id']==sid, f

# 3) Tiered admission: verified gap stays aggressive; tracked forecast needs
# more remaining ETA; truly empty observed-clear lanes use current gap maturity
# rather than recreating the old global ETA wall.
def st():
    return {
        'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
        'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
        'motion_ready':True,'visible_threat':False,'uncertain_incoming_count':0,
        'lane_visibility_ok':True,'lane_visibility_score':.95,'motion_corridor_ratio':.01,
        'motion_clear_dwell':1.0,'motion_current_clear_elapsed':.9,
        'dynamic_gap_mog_global_ratio':.01,'raw_risk':2.0,
        'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
        'stage_difficulty_score':.5,'live_speed_difficulty_score':.5,'motion_gap_support':30,
        'motion_gap_p25':1.7,'motion_live_ready':True,'czn_live_ready':True,
        'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.5,
        'eta_source_reliability':.8,'adaptive_confidence':.85,'dynamic_gap_confidence':.9,
        'recent_green_reliability':.8,'recent_green_failures':0,'recent_green_successes':0,
        'clear_dwell':1.0,'lane':'1','chicken_fresh':True,'target_lane_switches':0,
        'viewport_rebase_count':0,'dynamic_gap_cycle_id':1,'green_evidence_ok':False,
        'green_evidence_reason':'','active_tracks':0,'dynamic_gap_ready':False,'gap_open_ready':False,
        'slow_window_reason':'NO VERIFIED SLOW WINDOW','slow_window_profile_support':20,
        'slow_window_profile_confidence':.9,'slow_window_p25_gap':1.6,
    }

cfg={
    'enabled':True,'min_training_samples':0,'save_interval_seconds':9999,
    'absolute_min_eta_seconds':1.08,'verified_gap_min_eta_seconds':1.08,
    'observed_clear_min_eta_seconds':1.08,'forecast_min_eta_seconds':1.18,
    'forecast_slow_after_eta_penalty_seconds':.04,'forecast_slow_after_threshold_penalty':.004,
    'historical_slow_after_safe_gap_seconds':1.25,
    'observed_clear_min_elapsed_seconds':.70,'observed_clear_min_gap_p25_seconds':1.10,
    'historical_slow_after_current_gap_floor_seconds':1.25,'historical_slow_after_risk_trigger':.30,
    'green_commit_dwell_seconds':0.0,'green_commit_min_seconds':0.0,'green_commit_max_seconds':0.0,
}
with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),cfg)
    p.n=100
    p._predict=lambda s,x:(.96,'test')
    p._maybe_add_candidate=lambda *a,**k:None
    p._update_pending=lambda *a,**k:''

    a=st(); a['effective_eta']=1.09; a['motion_current_clear_elapsed']=.5
    out=p.apply(a,10.0)
    assert not out['v5_decision'] and out['v5_hard_reason']=='CLEAR MATURITY', out

    b=st(); b['effective_eta']=1.09
    out=p.apply(b,11.0)
    assert out['v5_gap_provenance']=='observed-clear'
    assert abs(out['v5_required_eta']-1.08)<1e-9
    assert out['v5_decision'], out

    c=st(); c['effective_eta']=1.12; c['active_tracks']=1
    out=p.apply(c,12.0)
    assert out['v5_gap_provenance']=='tracked-forecast'
    assert out['v5_required_eta']>=1.18
    assert not out['v5_decision'] and out['v5_hard_reason']=='FORECAST ETA', out

    d=st(); d['effective_eta']=1.12; d['dynamic_gap_ready']=True
    out=p.apply(d,13.0)
    assert out['v5_gap_provenance']=='verified-gap'
    assert abs(out['v5_required_eta']-1.08)<1e-9
    assert out['v5_decision'], out

    e=st(); e['effective_eta']=1.20; e['motion_gap_p25']=1.15
    e['slow_window_reason']='SLOW AFTER GAP 0.94<1.29'
    e['slow_window_profile_support']=100; e['slow_window_profile_confidence']=.78; e['slow_window_p25_gap']=.94
    out=p.apply(e,14.0)
    assert out['v5_historical_slow_after_risk']>0.0
    assert not out['v5_decision'] and out['v5_hard_reason']=='SLOW-AFTER PROFILE', out
    p._log_file.close()

print('PASS v527 visible outcome ownership + viewport rebase + tiered admission')
