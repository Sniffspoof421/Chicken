import json, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())['safe_window_v5']
with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(root,cfg)
    sw.n=max(sw.min_samples,500)
    sw.fitted=True
    # Reproduce the V5.3.8 late-session collapse: ML says ~0.23 while live
    # physical heuristic remains ~0.94.
    sw._predict=lambda s,x:(0.23,'session-collapsed')
    sw.last_heuristic_probability=0.94
    sw.last_longterm_probability=0.001
    sw.last_session_probability=0.004
    sw._threshold=lambda s:0.89
    sw._maybe_add_candidate=lambda *args,**kwargs: None
    base={
      'lane':1,'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
      'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
      'motion_ready':True,'dynamic_gap_ready':True,'dynamic_gap_cycle_id':99,
      'dynamic_gap_action_lease':0.55,'dynamic_gap_lease_required':0.10,
      'dynamic_gap_confidence':0.86,'dynamic_gap_preceding_busy_ok':True,
      'motion_preceding_busy_duration':0.50,'motion_gap_support':30,'motion_gap_p25':2.25,
      'gap_open_ready':False,'active_tracks':0,'motion_live_ready':True,'czn_live_ready':True,
      'slow_after_guard_active':False,'visible_threat':False,'uncertain_incoming_count':0,
      'lane_visibility_ok':True,'lane_visibility_score':1.0,
      'motion_corridor_ratio':0.0,'motion_corridor_clear':True,'motion_clear_dwell':0.35,
      'dynamic_gap_mog_global_ratio':0.0,'raw_risk':12.0,'risk':12.0,
      'effective_eta':2.20,'clear_dwell':0.4,'eta_source':'dynamic-gap',
      'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
      'target_lane_switches':0,'viewport_rebase_count':0,'chicken_fresh':True,
      'stage_difficulty_score':0.3,'live_speed_difficulty_score':0.4,
      'live_density_difficulty_score':0.3,'recent_green_reliability':0.5,
      'recent_green_failures':0,'recent_green_successes':0,'adaptive_confidence':0.8,
      'source_reliability':0.9,'crash_memory_safe_similarity':1.0,'slow_after_gap_score':0.0,
      'processing_fps':6.5,
    }
    out=sw.apply(dict(base),now=10.0)
    assert out['v5_decision'], out
    assert out['v5_verified_physical_override'], out
    assert out['v5_physical_override'], out
    assert out['v5_safe_probability'] < out['v5_admission_threshold'], out

    # Weak live physical evidence must NOT override ML.
    weak=dict(base); weak['dynamic_gap_cycle_id']=100; weak['dynamic_gap_confidence']=0.60
    out2=sw.apply(weak,now=11.0)
    assert not out2['v5_decision'], out2
    assert not out2['v5_verified_physical_override'], out2

    # Insufficient action lease stays a hard veto.
    short=dict(base); short['dynamic_gap_cycle_id']=101; short['dynamic_gap_action_lease']=0.20
    out3=sw.apply(short,now=12.0)
    assert not out3['v5_decision'] and out3['v5_hard_reason']=='ACTION LEASE', out3

    # Real vehicle hazard remains non-negotiable.
    hazard=dict(base); hazard['dynamic_gap_cycle_id']=102; hazard['visible_threat']=True
    out4=sw.apply(hazard,now=13.0)
    assert not out4['v5_decision'] and out4['v5_hard_reason']=='VISIBLE THREAT', out4
    sw._log_file.close()

print('PASS V5.3.9 strong verified physical override + hard-veto preservation')
