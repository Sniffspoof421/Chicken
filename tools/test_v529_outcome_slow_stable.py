import sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.outcome import GreenJumpOutcomeTracker
from app.risk import RiskEngine
from app.safe_window import SafeWindowPredictor

# 1) Outcome geometry must accept the real locked target distance, not the old
# clipped 320 px proxy. A ~440 px one-lane jump should become SUCCESS.
o=GreenJumpOutcomeTracker({
    'action_start_dx_px':18,'expected_jump_px':205,
    'jump_min_ratio':.58,'jump_max_ratio':1.32,'chain_ratio':1.55,
    'success_hold_seconds':.30,'success_grace_seconds':.70,
    'outcome_timeout_seconds':5.5,'stable_dx_px':14,
    'post_green_action_grace_seconds':2.8,'late_observation_window_seconds':6.0,
})
base={'cx':630.0,'cy':730.0}
st={'indicator_state':'CLEAR','green_confirmed':True,'lane':2,
    'target_lane_distance':440.0,'next_lane_distance':320.0,
    'effective_eta':1.5,'raw_risk':2.0,'display_risk':2.0,
    'chicken_fresh':True,'scene_pan_active':False,'viewport_hold':False,'vision_hold':False}
o.update(st,base,0.0)
assert o.current_signal is not None and abs(o.current_signal['expected_jump_px']-440.0)<1e-6,o.current_signal
# End green, then start action within grace.
st2=dict(st); st2['indicator_state']='WAIT'; st2['green_confirmed']=False
o.update(st2,base,.20)
ev=o.update(st2,{'cx':655.0,'cy':730.0},.45)
assert o.active_attempt is not None,ev
# Reach and stabilize at the true next lane.
o.update(st2,{'cx':1070.0,'cy':730.0},.75)
o.update(st2,{'cx':1071.0,'cy':730.0},.95)
ev=o.update(st2,{'cx':1071.0,'cy':730.0},1.30)
assert o.provisional is not None,ev
ev=o.update(st2,{'cx':1071.0,'cy':730.0},2.10)
assert any(x.get('outcome')=='success' for x in ev),ev

# 2) Learned type-speed memory can identify a likely slow approaching vehicle
# before its current track speed has fully settled into class S. Follower guard
# remains authoritative.
r=RiskEngine({
 'jump_crossing_seconds':.55,'safety_buffer_seconds':.30,
 'crossing_half_height_px':35,'min_approach_vy_px_s':12,
 'slow_window_enabled':True,'slow_window_min_profile_support':6,
 'slow_window_min_profile_confidence':.68,'slow_window_max_next_fast_prob':.35,
 'slow_window_min_p25_gap_seconds':.95,'slow_window_speed_margin':1.28,
 'slow_window_track_min_age':3,'slow_window_direction_consistency_min':.55,
 'slow_window_extra_margin_seconds':.12,
})
ch={'cx':100.0,'cy':700.0,'h':60.0}
trk={'id':10,'age':8,'cx':100.0,'cy':420.0,'h':30.0,
     'vy':45.0,'fit_vy':45.0,'net_vy':45.0,'direction_valid':True,
     'direction_consistency':.90}
cand={'track':trk,'class':'M','forward_class':'M','entry':2.5,'tti':5.0,
      'clearance':1.5,'overlap':False,'speed':45.0,'type_expected_speed':25.0}
profile={'ready':False,'support':1,'lane_support':1,'source':'lane','p25_gap':None,
         'median_gap':None,'p_fast_after_slow':1.0,'confidence':.1}
x=r._slow_window_geometry(l1={'candidates':[cand],'uncertain_incoming_count':0,'visible_threat':False},
    chicken=ch,slow_thr=34,fast_thr=57,profile=profile,upstream_eta=1.4,
    motion_view={'available':True,'clear':False,'ratio':.1},motion_clear_dwell=0,stage_score=.2)
assert x['ok'] and x['mode']=='slow-before',x

# 3) Once a GREEN is committed, a soft ML/provenance score drop must not turn
# it into a one-frame flash while every hard physical safety check still passes.
def sw_state(prob=.90):
    return {
      'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
      'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
      'motion_ready':True,'visible_threat':False,'uncertain_incoming_count':0,
      'lane_visibility_ok':True,'lane_visibility_score':.95,
      'motion_corridor_ratio':.01,'motion_clear_dwell':1.0,
      'motion_current_clear_elapsed':1.0,'dynamic_gap_mog_global_ratio':.01,
      'raw_risk':2.0,'crash_memory_score':0.0,'crash_memory_matches':0,
      'dynamic_gap_slow_guard':0,'effective_eta':1.45,
      'stage_difficulty_score':.8,'live_speed_difficulty_score':.8,
      'live_density_difficulty_score':.5,'stage_gap_p25':.9,
      'motion_gap_support':30,'motion_gap_p25':1.35,
      'motion_live_ready':True,'czn_live_ready':True,
      'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.5,
      'active_tracks':0,'dynamic_gap_ready':False,'gap_open_ready':False,
      'eta_source_reliability':.8,'adaptive_confidence':.85,
      'dynamic_gap_confidence':.8,'recent_green_reliability':.8,
      'recent_green_failures':0,'recent_green_successes':0,'clear_dwell':1.0,
      'lane':'1','chicken_fresh':True,'target_lane_switches':0,
      'viewport_rebase_count':0,'dynamic_gap_cycle_id':1,
      'green_evidence_ok':False,'green_evidence_reason':'',
      'slow_window_reason':'NO VERIFIED SLOW WINDOW','slow_window_profile_support':20,
      'slow_window_profile_confidence':.9,'slow_window_p25_gap':1.5,
      'test_prob':prob,
    }
cfg={
 'enabled':True,'min_training_samples':0,'save_interval_seconds':99999,
 'absolute_min_eta_seconds':1.08,'observed_clear_min_eta_seconds':1.08,
 'min_live_gap_p25_seconds':.95,'min_live_gap_support':8,'min_preceding_busy_seconds':.16,
 'min_motion_clear_dwell_seconds':.3,'observed_clear_min_elapsed_seconds':.7,
 'observed_clear_min_gap_p25_seconds':1.1,'base_probability_threshold':.90,
 'easy_probability_threshold':.91,'hard_probability_threshold':.88,'adaptive_probability_floor':.885,
 'observed_clear_probability_floor_easy':.85,'observed_clear_probability_floor_hard':.79,
 'gap_difficulty_easy_seconds':1.55,'gap_difficulty_hard_seconds':.8,
 'speed_difficulty_weight':.72,'gap_difficulty_weight':.88,'density_difficulty_weight':.55,
 'green_commit_dwell_seconds':.32,'green_commit_hard_add_seconds':-.04,
 'green_commit_min_seconds':.28,'green_commit_max_seconds':.34,
 'green_commit_dropout_grace_seconds':.42,'green_commit_exit_probability_margin':.035,
 'green_commit_exit_eta_margin_seconds':.06,'green_min_visible_hold_seconds':.65,
}
with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),cfg); p.n=100
    p._maybe_add_candidate=lambda *a,**k:None; p._update_pending=lambda *a,**k:''
    p._predict=lambda st,x:(float(st.get('test_prob',.90)),'test')
    good=sw_state(.90)
    p.apply(dict(good),10.0)
    out=p.apply(dict(good),10.31)
    assert out['v5_decision'],out
    # Abrupt probability drop while physical state remains hard-safe: keep it
    # visible during the minimum actionable lease.
    low=sw_state(.60)
    out=p.apply(dict(low),10.45)
    assert out['v5_decision'],out
    # A real hard hazard must still cancel immediately, even inside the lease.
    haz=sw_state(.95); haz['visible_threat']=True
    out=p.apply(haz,10.50)
    assert not out['v5_decision'] and out['v5_hard_reason']=='VISIBLE THREAT',out
    p._log_file.close()

print('PASS v529 outcome geometry + type slow-before + stable GREEN lease')
