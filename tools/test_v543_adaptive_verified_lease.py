import json, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())

def mk_state(lease=.34,conf=.86,support=24,gap=2.45,eta=2.20,raw=2.0,motion=0.0,mog=0.0):
    return {
      'lane':1,'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
      'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
      'motion_ready':True,'dynamic_gap_ready':True,'gap_open_ready':True,
      'dynamic_gap_cycle_id':77,'dynamic_gap_action_lease':lease,
      'dynamic_gap_lease_required':.10,'dynamic_gap_confidence':conf,
      'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.55,
      'active_tracks':0,'motion_live_ready':True,'czn_live_ready':True,
      'motion_gap_support':support,'motion_gap_p25':gap,'motion_current_clear_elapsed':.18,
      'motion_clear_dwell':.18,'slow_after_guard_active':False,'visible_threat':False,
      'uncertain_incoming_count':0,'lane_visibility_ok':True,'lane_visibility_score':1.0,
      'motion_corridor_ratio':motion,'motion_corridor_clear':True,
      'dynamic_gap_mog_global_ratio':mog,'raw_risk':raw,'risk':raw,
      'effective_eta':eta,'clear_dwell':.2,'eta_source':'dynamic-gap',
      'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
      'target_lane_switches':2,'viewport_rebase_count':0,'chicken_fresh':True,
      'stage_difficulty_score':.4,'live_speed_difficulty_score':.4,'live_density_difficulty_score':.4,
      'recent_green_reliability':.8,'recent_green_failures':0,'recent_green_successes':1,
      'adaptive_confidence':.85,'source_reliability':.9,'crash_memory_safe_similarity':1.0,
      'slow_after_gap_score':0.0,'processing_fps':6.35,
    }

# 1) Strong verified live gap with 0.34 s EXTRA lease is accepted even when ML
# has collapsed. RiskEngine's ~1.8 s required ETA already contains reaction,
# jump, safety and pipeline; this is just the extra presentation reserve.
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5']); sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(.30,'collapsed-ml')
    sw._threshold=lambda s:.89
    # _predict is stubbed, so set the physical heuristic explicitly.
    sw.last_heuristic_probability=.96
    out=sw.apply(mk_state(lease=.34),now=20.0)
    assert out['v5_verified_physical_override'],out
    assert out['v5_verified_gap_lease_tier']=='strong-physical',out
    assert out['v5_verified_gap_selected_lease_required'] <= .34+1e-9,out
    assert out['v5_decision'],out
    sw._log_file.close()

# 2) Weak/ML-only verified gap does NOT get the relaxed reserve. 0.40 s remains
# below the 0.42 s standard tier, preserving V5.4.2's safety for marginal gaps.
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5']); sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(.95,'test')
    sw._threshold=lambda s:.85
    sw.last_heuristic_probability=.80
    weak=mk_state(lease=.40,conf=.72,support=10,gap=1.95)
    out=sw.apply(weak,now=30.0)
    assert not out['v5_decision'],out
    assert out['v5_hard_reason']=='ACTION LEASE',out
    assert out['v5_verified_gap_lease_tier']=='standard',out
    assert out['v5_verified_gap_selected_lease_required'] >= .42-1e-9,out
    sw._log_file.close()

# 3) Same weaker verified state is allowed once it has a proper standard reserve
# and strong learned probability.
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5']); sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(.95,'test')
    sw._threshold=lambda s:.85
    sw.last_heuristic_probability=.80
    out=sw.apply(mk_state(lease=.46,conf=.72,support=10,gap=1.95),now=40.0)
    assert out['v5_verified_gap_lease_tier']=='standard',out
    assert out['v5_decision'],out
    sw._log_file.close()

# 4) Strong physical candidate below 0.32 s remains blocked; the relaxed tier is
# not a zero-margin shortcut.
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5']); sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(.30,'collapsed-ml')
    sw._threshold=lambda s:.89
    sw.last_heuristic_probability=.96
    out=sw.apply(mk_state(lease=.29),now=50.0)
    assert not out['v5_decision'],out
    assert out['v5_hard_reason']=='ACTION LEASE',out
    sw._log_file.close()

print('PASS V5.4.3 adaptive verified-gap lease: strong physics 0.32 tier + standard 0.42 tier')
