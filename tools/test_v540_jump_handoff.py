import json, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Reproduce V5.3.9 first-jump failure: GREEN x~193 -> action -> landing x~630.
# The target lock advances to the next lane (ARRIVED). That must immediately
# close the GREEN as success instead of remaining JUMPING until a later reset.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base={
    'indicator_state':'CLEAR','green_confirmed':True,'lane':1,
    'eta_source':'v5-safe-window','effective_eta':2.1,
    'raw_risk':11.0,'display_risk':11.0,
    'target_lane_distance':415.0,'target_lane_x':608.0,
    'target_lane_switches':1,'target_lane_lock_reason':'HOLD_SAME',
    'viewport_rebase_count':0,
}
o.update(base,{'cx':193.0,'detected':True},10.00)
off=dict(base); off['indicator_state']='WAIT'
ev=o.update(off,{'cx':335.0,'detected':True},10.33)
assert any(x.get('kind')=='action_started' for x in ev),ev
arr=dict(off)
arr.update({
    'target_lane_x':1072.0,
    'target_lane_switches':2,
    'target_lane_lock_reason':'ARRIVED',
})
ev=o.update(arr,{'cx':630.0,'detected':True},10.65)
success=[x for x in ev if x.get('outcome')=='success']
assert success,ev
assert success[0].get('success_reason')=='target_arrival_handoff',success
assert o.active_attempt is None and o.provisional is None
assert o.status()['green_target_arrival_successes']==1

# 2) If chicken CV disappears and no ARRIVED proof exists, never stay JUMPING
# for many seconds. Timeout is UNKNOWN (no supervised failure).
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.active_attempt={
    'signal_id':9,'baseline_x':190.0,'action_start_x':330.0,
    'action_start_ts':20.0,'expected_jump_px':440.0,
    'last_x':330.0,'max_x':330.0,'stable_since':None,
}
ev=o.update({'indicator_state':'WAIT'},None,21.40)
unk=[x for x in ev if x.get('outcome')=='unknown']
assert unk and unk[0].get('unknown_reason')=='chicken_detection_timeout',ev
assert o.active_attempt is None

# 3) Strong mature observed-clear state at ~1.42s ETA can be admitted from
# CURRENT traffic physics. This is NOT a generic threshold lowering.
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5'])
    sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(0.25,'collapsed-ml')
    sw._threshold=lambda s:0.90
    sw.last_heuristic_probability=.93
    state={
        'lane':1,'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
        'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
        'motion_ready':True,'dynamic_gap_ready':False,'gap_open_ready':False,
        'active_tracks':0,'motion_live_ready':True,'czn_live_ready':False,
        'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.55,
        'motion_gap_support':45,'motion_gap_p25':1.85,
        'motion_current_clear_elapsed':1.35,'motion_clear_dwell':1.35,
        'slow_after_guard_active':False,'visible_threat':False,'uncertain_incoming_count':0,
        'lane_visibility_ok':True,'lane_visibility_score':1.0,
        'motion_corridor_ratio':0.0,'motion_corridor_clear':True,
        'dynamic_gap_mog_global_ratio':0.0,'raw_risk':11.0,'risk':11.0,
        'effective_eta':1.42,'clear_dwell':1.35,'eta_source':'clear-zone',
        'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
        'target_lane_switches':2,'viewport_rebase_count':0,'chicken_fresh':True,
        'stage_difficulty_score':0.2,'live_speed_difficulty_score':0.2,
        'live_density_difficulty_score':0.2,'recent_green_reliability':0.8,
        'recent_green_failures':0,'recent_green_successes':1,
        'adaptive_confidence':0.85,'source_reliability':0.9,
        'crash_memory_safe_similarity':1.0,'slow_after_gap_score':0.0,
        'dynamic_gap_action_lease':0.0,'dynamic_gap_lease_required':0.0,
    }
    # force physical heuristic for this regression to model supplied run
    sw._heuristic_probability=lambda s: .93
    out=sw.apply(dict(state),now=30.0)
    assert out['v5_sustained_observed_override'],out
    assert out['v5_required_eta'] <= 1.40+1e-9,out
    assert out['v5_raw_decision'] and out['v5_decision'],out

    # 4) A verified GREEN whose special dynamic lease expires may stay visible
    # through a policy-only FORECAST ETA flip for the bounded display hold.
    sw.pending.clear()
    sw._commit_key=None
    sw._commit_since=None
    sw._commit_last_good=None
    sw._commit_started=None
    sw._commit_active=False
    sw._verified_active_cycle=None
    sw._verified_hold_until=0.0
    sw._verified_hold_key=None
    vg=dict(state)
    vg.update({
        'dynamic_gap_ready':True,'dynamic_gap_cycle_id':88,
        'dynamic_gap_action_lease':0.40,'dynamic_gap_lease_required':0.10,
        'dynamic_gap_confidence':.90,'motion_current_clear_elapsed':0.0,
        'effective_eta':2.10,
    })
    first=sw.apply(vg,now=40.0)
    assert first['v5_decision'],first
    follow=dict(state)
    follow.update({
        'motion_current_clear_elapsed':0.35,
        'effective_eta':1.42,
        # Make sustained override unavailable so this specifically tests hold.
        'motion_gap_support':12,'motion_gap_p25':1.60,
    })
    second=sw.apply(follow,now=40.45)
    assert second['v5_active_green_hold_override'],second
    assert second['v5_decision'],second
    assert second['green_required_eta'] <= cfg['safe_window_v5']['active_green_hold_min_eta_seconds']+1e-9
    sw._log_file.close()

print('PASS V5.4.0 target-arrival success + missing-CV release + sustained observed clear + bounded GREEN hold')
