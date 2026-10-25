from pathlib import Path
import tempfile
from app.safe_window import SafeWindowPredictor
from app.outcome import GreenJumpOutcomeTracker

base = {
    'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
    'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
    'motion_ready':True,'slow_after_guard_active':False,'visible_threat':False,
    'uncertain_incoming_count':0,'lane_visibility_ok':True,'lane_visibility_score':.9,
    'motion_corridor_ratio':0.0,'motion_clear_dwell':1.0,'dynamic_gap_mog_global_ratio':0.0,
    'raw_risk':2.0,'effective_eta':1.35,'crash_memory_score':0.0,'crash_memory_matches':0,
    'dynamic_gap_slow_guard':0,'active_tracks':0,'motion_live_ready':True,'czn_live_ready':True,
    'dynamic_gap_preceding_busy_ok':False,'motion_preceding_busy_duration':0.0,
    'motion_gap_support':30,'motion_gap_p25':1.6,
}
with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td), {'enabled':True,'absolute_min_eta_seconds':1.08,
        'min_live_gap_p25_seconds':.95,'min_live_gap_support':8,'min_preceding_busy_seconds':.16})
    ok,reason=p._hard_veto(dict(base))
    assert not ok and reason=='LIVE GAP UNVERIFIED', (ok,reason)
    b=dict(base); b['dynamic_gap_preceding_busy_ok']=True; b['motion_preceding_busy_duration']=.4
    ok,reason=p._hard_veto(b); assert ok,(ok,reason)
    c=dict(base); c['active_tracks']=2
    ok,reason=p._hard_veto(c); assert ok,(ok,reason)

cfg={'post_green_action_grace_seconds':2.1,'late_observation_window_seconds':4.0,
     'action_start_dx_px':18,'expected_jump_px':440}
o=GreenJumpOutcomeTracker(cfg)
state={'indicator_state':'CLEAR','lane':1,'eta_source':'v5-safe-window','effective_eta':1.3,
       'raw_risk':2,'display_risk':2,'scene_pan_active':False,'chicken_fresh':True}
ch={'cx':100.0}
o.update(state,ch,0.0)
state['indicator_state']='WAIT'
o.update(state,ch,0.5)
# Movement appears 1.5 s after GREEN ended: V5.2 called this late/unattributed.
ev=o.update(state,{'cx':125.0},2.0)
assert any(x.get('kind')=='action_started' for x in ev), ev
assert o.late_unattributed==0, o.late_unattributed
print('PASS v5.2.1 live-gap and extended-attribution regression')
