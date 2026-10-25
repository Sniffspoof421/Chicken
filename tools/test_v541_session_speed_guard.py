import json, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.risk import RiskEngine
from app.safe_window import SafeWindowPredictor
from app.outcome import GreenJumpOutcomeTracker

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Current-session fast traffic must remain an observed-clear speed guard
# even if the recent 180 s window has gone quiet.
r=RiskEngine(cfg['risk'])
session_events=[
    {'speed':v,'forward_speed':v}
    for v in [403,542,515,620,690,705,720,735,760,780,680,710,730,750]
]
ctx=r._czn_speed_context(
    tracks=[], segment_events=[], traffic={'speed_p90':155},
    fast_thr=155, now=1000.0, historical_event_count=500,
    historical_speed_p95=161.0, session_events=session_events
)
assert ctx['speed_reference'] <= 400.1, ctx
assert ctx['session_speed_support'] >= 12,ctx
assert ctx['session_speed_guard_reference'] >= 690.0,ctx
assert ctx['observed_clear_speed_reference'] >= ctx['session_speed_guard_reference'],ctx

# 2) Reproduce failed V5.4.0 GREEN: ETA~1.43 using 392 px/s.
# Session guard ~700 px/s makes conservative policy ETA ~0.80 s -> reject.
with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(root,cfg['safe_window_v5'])
    sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(0.93,'test')
    sw._threshold=lambda s:0.89
    state={
        'lane':1,'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
        'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
        'motion_ready':True,'dynamic_gap_ready':False,'gap_open_ready':False,
        'active_tracks':0,'motion_live_ready':True,'czn_live_ready':False,
        'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.55,
        'motion_gap_support':40,'motion_gap_p25':2.05,
        'motion_current_clear_elapsed':1.30,'motion_clear_dwell':1.30,
        'slow_after_guard_active':False,'visible_threat':False,'uncertain_incoming_count':0,
        'lane_visibility_ok':True,'lane_visibility_score':1.0,
        'motion_corridor_ratio':0.0,'motion_corridor_clear':True,
        'dynamic_gap_mog_global_ratio':0.0,'raw_risk':2.0,'risk':2.0,
        'effective_eta':1.43,'clear_dwell':1.30,'eta_source':'clear-zone',
        'czn_speed_reference':392.0,'czn_observed_clear_speed_reference':700.0,
        'czn_session_speed_guard_reference':700.0,'czn_session_speed_support':19,
        'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
        'target_lane_switches':2,'viewport_rebase_count':0,'chicken_fresh':True,
        'stage_difficulty_score':0.2,'live_speed_difficulty_score':0.2,
        'live_density_difficulty_score':0.2,'recent_green_reliability':0.8,
        'recent_green_failures':0,'recent_green_successes':1,
        'adaptive_confidence':0.85,'source_reliability':0.9,
        'crash_memory_safe_similarity':1.0,'slow_after_gap_score':0.0,
        'dynamic_gap_action_lease':0.0,'dynamic_gap_lease_required':0.0,
    }
    out=sw.apply(dict(state),now=30.0)
    assert out['v5_observed_clear_guard_eta'] < 0.90,out
    assert not out['v5_decision'],out
    assert out['v5_hard_reason']=='FORECAST ETA',out

    # 3) A genuinely long, strongly supported observed-clear window can still
    # bypass collapsed ML without lowering the physical ETA requirement.
    good=dict(state)
    good.update({
        'effective_eta':3.20,
        'motion_gap_support':45,
        'motion_gap_p25':2.10,
        'motion_current_clear_elapsed':1.45,
        'motion_clear_dwell':1.45,
        'raw_risk':8.0,'risk':8.0,
    })
    sw._predict=lambda s,x:(0.20,'collapsed-ml')
    sw._heuristic_probability=lambda s:.94
    sw.last_heuristic_probability=.94
    out2=sw.apply(good,now=31.0)
    assert out2['v5_observed_clear_guard_eta'] >= 1.62,out2
    assert out2['v5_sustained_observed_override'],out2
    assert out2['v5_decision'],out2

    sw._log_file.close()

# 4) Verified dynamic gap is direct timing and must NOT be scaled by the
# session observed-clear speed guard.
with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(root,cfg['safe_window_v5'])
    sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(.95,'test')
    sw._threshold=lambda s:.89
    vg=dict(state)
    vg.update({
        'dynamic_gap_ready':True,'dynamic_gap_cycle_id':90,
        'dynamic_gap_action_lease':0.90,'dynamic_gap_lease_required':0.10,
        'dynamic_gap_confidence':.90,'effective_eta':2.0,
        'motion_current_clear_elapsed':0.0,
    })
    out3=sw.apply(vg,now=32.0)
    assert out3['v5_gap_provenance']=='verified-gap',out3
    assert abs(out3['v5_policy_eta']-2.0)<1e-6,out3
    assert out3['v5_decision'],out3
    sw._log_file.close()

# 5) Successful one-lane landing often advances target switch while lock reason
# is HOLD_SAME, not ARRIVED. That must close the jump and release next-lane analysis.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base={
    'indicator_state':'CLEAR','green_confirmed':True,'lane':2,
    'eta_source':'v5-safe-window','effective_eta':2.0,
    'raw_risk':8.0,'display_risk':8.0,
    'target_lane_distance':438.0,'target_lane_x':1070.0,
    'target_lane_switches':224,'target_lane_lock_reason':'HOLD_SAME',
    'viewport_rebase_count':0,
}
o.update(base,{'cx':632.0,'detected':True},40.0)
off=dict(base); off['indicator_state']='WAIT'
e=o.update(off,{'cx':769.0,'detected':True},40.20)
assert any(x.get('kind')=='action_started' for x in e),e
land=dict(off)
land.update({
    'target_lane_x':1512.0,
    'target_lane_switches':225,
    'target_lane_lock_reason':'HOLD_SAME',
})
e=o.update(land,{'cx':1072.0,'detected':True},40.45)
succ=[x for x in e if x.get('outcome')=='success']
assert succ and succ[0].get('success_reason')=='target_switch_handoff',e
assert o.active_attempt is None and o.provisional is None

# 6) Merely reaching lane geometry without target ownership advance is NOT success.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.active_attempt={
    'signal_id':5,'baseline_x':192.0,'action_start_x':339.0,
    'action_start_ts':50.0,'expected_jump_px':413.0,'last_x':339.0,'max_x':339.0,
    'target_switches_at_signal':215,'viewport_rebase_at_signal':0,
    'target_lane_x_at_signal':605.0,
}
state={
    'target_lane_switches':215,'viewport_rebase_count':0,
    'target_lane_lock_reason':'REANCHOR','target_lane_x':1073.0,
}
assert o._target_arrival_success(state,{'cx':637.0},50.5) is None

print('PASS V5.4.1 session-fast observed-clear guard + safe target-switch handoff')
