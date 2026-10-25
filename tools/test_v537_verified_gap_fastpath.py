import json, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())['safe_window_v5']

with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(root,cfg)
    sw.n=max(sw.min_samples,100)
    sw.fitted=True
    # Keep this regression focused on physical admission/lease logic.
    sw._predict=lambda s,x:(0.93,'test')
    sw._threshold=lambda s:0.89

    base={
        'lane':1,'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
        'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
        'motion_ready':True,'dynamic_gap_ready':True,'dynamic_gap_cycle_id':41,
        'dynamic_gap_action_lease':0.95,'dynamic_gap_lease_required':0.10,
        'gap_open_ready':False,'active_tracks':0,'motion_live_ready':True,
        'czn_live_ready':True,'dynamic_gap_preceding_busy_ok':True,
        'motion_preceding_busy_duration':0.50,'motion_gap_support':20,'motion_gap_p25':2.4,
        'slow_after_guard_active':False,'visible_threat':False,'uncertain_incoming_count':0,
        'lane_visibility_ok':True,'lane_visibility_score':1.0,
        'motion_corridor_ratio':0.0,'motion_corridor_clear':True,
        # The old bug: first verified frame had 0 clear dwell and was rejected.
        'motion_clear_dwell':0.0,'motion_current_clear_elapsed':0.0,
        'dynamic_gap_mog_global_ratio':0.0,'raw_risk':2.0,'risk':2.0,
        'effective_eta':2.6,'clear_dwell':0.0,'eta_source':'dynamic-gap',
        'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
        'target_lane_switches':0,'viewport_rebase_count':0,'chicken_fresh':True,
        'stage_difficulty_score':0.7,'live_speed_difficulty_score':0.8,
        'live_density_difficulty_score':0.7,'recent_green_reliability':0.8,
        'recent_green_failures':0,'recent_green_successes':0,
        'adaptive_confidence':0.85,'source_reliability':0.9,
        'crash_memory_safe_similarity':1.0,'slow_after_gap_score':0.0,
    }

    out=sw.apply(dict(base),now=10.0)
    assert out['v5_hard_ok'], out
    assert out['v5_verified_gap_fastpath'], out
    assert out['v5_commit_required'] == 0.0, out
    assert out['v5_decision'], out

    # Same physical cycle may remain GREEN even after the extra lease shrinks;
    # RiskEngine's dynamic_gap_ready still guarantees its own minimum lease.
    cont=dict(base); cont['dynamic_gap_action_lease']=0.20
    out2=sw.apply(cont,now=10.30)
    assert out2['v5_hard_ok'], out2
    assert out2['v5_decision'], out2

    # A real hazard must still cancel immediately.
    hazard=dict(cont); hazard['visible_threat']=True
    out3=sw.apply(hazard,now=10.31)
    assert not out3['v5_decision'] and out3['v5_hard_reason']=='VISIBLE THREAT', out3

    # A NEW cycle with too little reaction lease is not admitted.
    low=dict(base); low['dynamic_gap_cycle_id']=42; low['dynamic_gap_action_lease']=0.20
    out4=sw.apply(low,now=11.0)
    assert not out4['v5_decision'] and out4['v5_hard_reason']=='ACTION LEASE', out4

    # Forecast/observed-clear policy remains strict; V5.3.7 only changes verified gaps.
    assert sw._required_eta_for_green({},'observed-clear',0.0) >= 1.58
    assert sw._required_eta_for_green({},'tracked-forecast',0.0) >= 1.58
    sw._log_file.close()

print('PASS V5.3.7 verified-gap fast path + actionable lease + hard-hazard cancel')
