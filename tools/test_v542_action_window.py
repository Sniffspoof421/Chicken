import json, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())

# 1) V5.4.1 false-JUMPING regression: lane step ~440, detector wobble 631->702
# is only 71 px and must NOT own a GREEN action anymore.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base={
 'indicator_state':'CLEAR','green_confirmed':True,'lane':2,
 'eta_source':'v5-safe-window','effective_eta':2.55,'raw_risk':2.0,'display_risk':2.0,
 'target_lane_distance':440.0,'target_lane_x':1071.0,'target_lane_switches':25,
 'target_lane_lock_reason':'HOLD_SAME','viewport_rebase_count':3,
}
o.update(base,{'cx':631.0,'detected':True},10.0)
off=dict(base); off['indicator_state']='WAIT'
ev=o.update(off,{'cx':702.0,'detected':True},10.3)
assert not any(x.get('kind')=='action_started' for x in ev),ev
assert o.active_attempt is None,o.status()
# Real first-jump movement ~138 px still starts.
ev=o.update(off,{'cx':769.0,'detected':True},10.45)
assert any(x.get('kind')=='action_started' for x in ev),ev

# Common SafeWindow test state.
def mk_state(lease=.80,conf=.82,support=10,gap=2.80,eta=2.65,raw=2.0,motion=0.0,mog=0.0):
 return {
  'lane':1,'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
  'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
  'motion_ready':True,'dynamic_gap_ready':True,'gap_open_ready':True,
  'dynamic_gap_cycle_id':77,'dynamic_gap_action_lease':lease,
  'dynamic_gap_lease_required':.12,'dynamic_gap_confidence':conf,
  'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.5,
  'active_tracks':0,'motion_live_ready':True,'czn_live_ready':True,
  'motion_gap_support':support,'motion_gap_p25':gap,'motion_current_clear_elapsed':.2,
  'motion_clear_dwell':.2,'slow_after_guard_active':False,'visible_threat':False,
  'uncertain_incoming_count':0,'lane_visibility_ok':True,'lane_visibility_score':1.0,
  'motion_corridor_ratio':motion,'motion_corridor_clear':True,
  'dynamic_gap_mog_global_ratio':mog,'raw_risk':raw,'risk':raw,
  'effective_eta':eta,'clear_dwell':.2,'eta_source':'dynamic-gap',
  'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
  'target_lane_switches':2,'viewport_rebase_count':0,'chicken_fresh':True,
  'stage_difficulty_score':.4,'live_speed_difficulty_score':.4,'live_density_difficulty_score':.4,
  'recent_green_reliability':.8,'recent_green_failures':0,'recent_green_successes':1,
  'adaptive_confidence':.85,'source_reliability':.9,'crash_memory_safe_similarity':1.0,
  'slow_after_gap_score':0.0,
 }

# 2) Marginal verified gap with only 0.40 s extra lease must not flash GREEN.
with tempfile.TemporaryDirectory() as td:
 r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
 sw=SafeWindowPredictor(r,cfg['safe_window_v5']); sw.n=max(sw.min_samples,100); sw.fitted=True
 sw._predict=lambda s,x:(.95,'test'); sw._threshold=lambda s:.85
 x=mk_state(lease=.40)
 out=sw.apply(x,now=20.0)
 assert not out['v5_decision'],out
 assert out['v5_hard_reason']=='ACTION LEASE',out
 sw._log_file.close()

# 3) Strong live gap that V5.4.1 ML rejected must now use the strict physical override.
with tempfile.TemporaryDirectory() as td:
 r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
 sw=SafeWindowPredictor(r,cfg['safe_window_v5']); sw.n=max(sw.min_samples,100); sw.fitted=True
 sw._predict=lambda s,x:(.32,'collapsed-ml'); sw._threshold=lambda s:.89
 sw._heuristic_probability=lambda s:.965
 sw.last_heuristic_probability=.965
 out=sw.apply(mk_state(lease=.80,conf=.82,support=10,gap=2.85),now=30.0)
 assert out['v5_verified_physical_override'],out
 assert out['v5_decision'],out
 sw._log_file.close()

# 4) Once GREEN is committed, early motion rise must cancel it immediately.
with tempfile.TemporaryDirectory() as td:
 r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
 sw=SafeWindowPredictor(r,cfg['safe_window_v5']); sw.n=max(sw.min_samples,100); sw.fitted=True
 sw._predict=lambda s,x:(.95,'test'); sw._threshold=lambda s:.85
 first=sw.apply(mk_state(lease=.80),now=40.0)
 assert first['v5_decision'],first
 danger=mk_state(lease=.65,raw=35.0,motion=.07,mog=.02)
 second=sw.apply(danger,now=40.15)
 assert not second['v5_decision'],second
 assert second['v5_hard_reason']=='GREEN MOTION RISE',second
 sw._log_file.close()


# 5) Unacted GREEN cooldown is cycle-aware: same gap suppressed, a new verified
# cycle is not hidden behind the old blanket multi-second blackout.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.current_signal={'signal_id':1,'start_ts':60.0,'end_ts':60.0,'duration':0.0,'v5_cycle_id':100,'baseline_x':190.0}
o.pending_signal=o.current_signal; o.current_signal=None
o._expire_signal(60.70)
assert not o.green_display_allowed(61.0,100)
assert o.green_display_allowed(61.0,101)

print('PASS V5.4.2 stable action-window GREEN + anti-jitter action ownership + strong missed-gap override + cycle-aware rearm')
