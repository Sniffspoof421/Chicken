import json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())

with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5'])
    sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(.97,'test')
    sw._threshold=lambda s:.90
    sw._heuristic_probability=lambda s:.97
    sw.last_heuristic_probability=.97

    base={
      'lane':1,'difficulty_mode':'NORMAL',
      'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
      'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
      'motion_ready':True,'dynamic_gap_ready':True,'gap_open_ready':False,
      'dynamic_gap_cycle_id':10,'dynamic_gap_preceding_busy_ok':True,
      'dynamic_gap_confidence':.96,'dynamic_gap_action_lease':.70,
      'dynamic_gap_lease_required':.08,'dynamic_gap_mog_global_ratio':0.0,
      'motion_live_ready':True,'czn_live_ready':True,'motion_preceding_busy_duration':.45,
      'motion_gap_support':20,'motion_gap_p25':2.3,
      'motion_corridor_ratio':0.0,'motion_corridor_clear':True,
      'motion_clear_dwell':0.0,'motion_current_clear_elapsed':0.0,
      'dynamic_gap_effective_clear_elapsed':0.0,
      'active_tracks':0,'slow_after_guard_active':False,'visible_threat':False,
      'uncertain_incoming_count':0,'lane_visibility_ok':True,'lane_visibility_score':1.0,
      'raw_risk':2.0,'risk':2.0,'effective_eta':2.5,'clear_dwell':0.0,
      'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
      'target_lane_switches':1,'viewport_rebase_count':0,'processing_fps':7.0,
      'stage_difficulty_score':.3,'live_speed_difficulty_score':.3,
      'live_density_difficulty_score':.2,'recent_green_reliability':.8,
      'recent_green_failures':0,'recent_green_successes':1,'adaptive_confidence':.9,
      'source_reliability':.9,'crash_memory_safe_similarity':1.0,'slow_after_gap_score':0.0,
    }

    # First clear frame after a pass is NOT GREEN anymore.
    a=sw.apply(dict(base),now=10.0)
    assert not a['v5_decision'],a
    assert a['v5_hard_reason']=='POST PASS SETTLE',a
    assert abs(a['v5_post_pass_settle_required']-.24)<1e-9,a

    # Still settling at 0.18 s.
    b=dict(base); b.update({'motion_clear_dwell':.18,'motion_current_clear_elapsed':.18,
                            'dynamic_gap_effective_clear_elapsed':.18,
                            'dynamic_gap_action_lease':.52})
    b=sw.apply(b,now=10.18)
    assert not b['v5_decision'] and b['v5_hard_reason']=='POST PASS SETTLE',b

    # At >=0.24 s clean tail, same strong gap becomes GO-NOW GREEN.
    c=dict(base); c.update({'motion_clear_dwell':.26,'motion_current_clear_elapsed':.26,
                            'dynamic_gap_effective_clear_elapsed':.26,
                            'dynamic_gap_action_lease':.44})
    c=sw.apply(c,now=10.26)
    assert c['v5_post_pass_ready'],c
    assert c['v5_verified_gap_lease_tier']=='strong-physical',c
    assert c['v5_verified_gap_selected_lease_required'] <= .22+1e-9,c
    assert c['v5_decision'],c

    # A still-alive target-lane track adds 0.10 s tail clearance in NORMAL.
    sw.pending.clear()
    sw._commit_active=False; sw._commit_since=None; sw._commit_started=None; sw._commit_last_good=None
    sw._verified_active_cycle=None; sw._verified_hold_until=0.0; sw._verified_hold_key=None
    d=dict(base); d.update({'active_tracks':1,'motion_clear_dwell':.27,'motion_current_clear_elapsed':.27,
                            'dynamic_gap_effective_clear_elapsed':.27,'dynamic_gap_action_lease':.55,
                            'dynamic_gap_cycle_id':11})
    d=sw.apply(d,now=10.50)
    assert not d['v5_decision'] and d['v5_hard_reason']=='POST PASS SETTLE',d
    assert abs(d['v5_post_pass_settle_required']-.34)<1e-9,d

    sw.pending.clear()
    e=dict(d); e.update({'motion_clear_dwell':.36,'motion_current_clear_elapsed':.36,
                         'dynamic_gap_effective_clear_elapsed':.36,'dynamic_gap_action_lease':.46})
    e=sw.apply(e,now=10.60)
    assert e['v5_post_pass_ready'],e

    # Harder modes wait longer before GO-NOW.
    hard=dict(base); hard['difficulty_mode']='HARD'
    assert abs(sw._post_pass_settle_requirement(hard)-.30)<1e-9
    extreme=dict(base); extreme['difficulty_mode']='EXTREME'
    assert abs(sw._post_pass_settle_requirement(extreme)-.34)<1e-9

    sw._log_file.close()

print('PASS V5.4.5 centered GREEN post-pass settle + track-tail timing')

# Preserve V5.4.2 action ownership: detector wobble is not a jump.
from app.outcome import GreenJumpOutcomeTracker
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base_o={
 'indicator_state':'CLEAR','green_confirmed':True,'lane':2,
 'eta_source':'v5-safe-window','effective_eta':2.55,'raw_risk':2.0,'display_risk':2.0,
 'target_lane_distance':440.0,'target_lane_x':1071.0,'target_lane_switches':25,
 'target_lane_lock_reason':'HOLD_SAME','viewport_rebase_count':3,
}
o.update(base_o,{'cx':631.0,'detected':True},30.0)
off=dict(base_o); off['indicator_state']='WAIT'
ev=o.update(off,{'cx':702.0,'detected':True},30.3)
assert not any(x.get('kind')=='action_started' for x in ev),ev
ev=o.update(off,{'cx':769.0,'detected':True},30.45)
assert any(x.get('kind')=='action_started' for x in ev),ev

# Cycle-aware rearm remains intact.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.current_signal={'signal_id':1,'start_ts':60.0,'end_ts':60.0,'duration':0.0,'v5_cycle_id':100,'baseline_x':190.0}
o.pending_signal=o.current_signal; o.current_signal=None
expire_at=60.0+float(cfg['outcome_learning']['post_green_action_grace_seconds'])+.05
o._expire_signal(expire_at)
assert not o.green_display_allowed(expire_at+.10,100)
assert o.green_display_allowed(expire_at+.10,101)

print('PASS V5.4.5 preserved anti-jitter action ownership + cycle-aware rearm')
