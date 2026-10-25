import sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.chicken import ChickenDetector
from app.target_lane import StableNextLane
from app.safe_window import SafeWindowPredictor

# 1) A one-lane apparent chicken teleport must not move identity on one frame.
c=ChickenDetector({
    'max_position_jump_px':260,'max_smooth_distance_px':175,
    'jump_confirm_frames':3,'jump_confirm_radius_px':85,
    'large_move_confirm_fraction':.50,'large_move_min_px':120,
})
c.set_lane_spacing(440.0)
c.last={'cx':100.0,'cy':500.0,'w':100.0,'h':100.0,'x':50.0,'y':450.0,'confidence':.9}
far={'cx':540.0,'cy':500.0,'w':100.0,'h':100.0,'x':490.0,'y':450.0,'confidence':.9,'geom_scale':1.0,'detected':True}
r1=c._confirm_candidate(dict(far)); assert not r1.get('detected',True) and r1.get('pending_position')
r2=c._confirm_candidate(dict(far)); assert not r2.get('detected',True) and r2.get('pending_position')
r3=c._confirm_candidate(dict(far)); assert r3.get('confirmed_teleport') and abs(r3['cx']-540.0)<1e-6

# 2) Once the confirmed chicken reaches the old lane, target advances to the
# immediate next lane instead of remaining behind.
t=StableNextLane(switch_min_seconds=.18)
assert t.update([(1,540.0)],100.0,440.0,1.0)==(1,540.0)
out=t.update([(2,980.0)],540.0,440.0,1.5)
assert out==(2,980.0),out

base={
 'processing_healthy':True,'sensor_desync':False,'tracking_starvation':True,
 'tracking_rewarm':False,'viewport_hold':False,'vision_hold':False,
 'target_green_geometry_ok':True,'motion_ready':True,'visible_threat':False,
 'uncertain_incoming_count':0,'lane_visibility_ok':True,'lane_visibility_score':.95,
 'motion_corridor_ratio':0.0,'motion_clear_dwell':1.0,'dynamic_gap_mog_global_ratio':0.0,
 'raw_risk':2.0,'effective_eta':1.4,'crash_memory_score':0.0,'crash_memory_matches':0,
 'dynamic_gap_slow_guard':0,'stage_difficulty_score':.5,'lane':'1','chicken_fresh':True,
 'clear_dwell':1.0,'eta_source_reliability':.8,'adaptive_confidence':.8,
 'recent_green_reliability':.8,'processing_fps':6.0,'slow_after_guard_active':False,
}
with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),{'enabled':True,'min_training_samples':999,'absolute_min_eta_seconds':1.0,'min_motion_clear_dwell_seconds':.3})
    # Zero tracks/starvation is diagnostic only in V5.2; empty lanes are valid.
    ok,reason=p._hard_veto(dict(base)); assert ok,(ok,reason)
    # BEFORE slow: visible/motion/raw-risk from the slow anchor itself may be
    # accepted when direct geometry and follower timing are verified.
    s=dict(base,visible_threat=True,motion_corridor_ratio=.18,raw_risk=95.0,
           slow_window_mode='slow-before',slow_window_eta=1.55,
           slow_window_required_eta=1.20,slow_window_follower_eta=None,
           dynamic_gap_slow_guard=1)
    ok,reason=p._hard_veto(s); assert ok,(ok,reason)
    # AFTER slow: default block until learned follower/headway evidence is strong.
    s=dict(base,slow_after_guard_active=True,slow_window_mode='',recent_slow_pass_age=.6)
    ok,reason=p._hard_veto(s); assert not ok and reason=='AFTER SLOW GUARD',(ok,reason)
    s=dict(base,slow_after_guard_active=True,slow_window_mode='slow-after',
           slow_window_profile_support=10,slow_window_profile_confidence=.82,
           slow_window_p25_gap=1.70,slow_window_p_fast=.12,
           slow_window_follower_eta=1.80,slow_window_eta=1.65,
           slow_window_required_eta=1.20)
    ok,reason=p._hard_veto(s); assert ok,(ok,reason)
    p._log_file.close()
print('V5.2 identity + target-follow + asymmetric slow checks: PASS')
