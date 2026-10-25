from app.outcome import GreenJumpOutcomeTracker
cfg={
 'post_green_action_grace_seconds':2.1,'late_observation_window_seconds':4.0,
 'action_start_dx_px':18,'expected_jump_px':205,'stationary_dx_px':10,
}
o=GreenJumpOutcomeTracker(cfg)
state={'indicator_state':'CLEAR','lane':1,'eta_source':'v5-safe-window','effective_eta':1.4,
       'raw_risk':10,'display_risk':10,'v5_feature_vector':[.1]*18,
       'v5_safe_probability':.94,'v5_safe_threshold':.90,'dynamic_gap_cycle_id':7}
ch={'cx':100.0}
o.update(state,ch,10.0)
# Signal ends with no visible action onset.
state2=dict(state); state2['indicator_state']='WAIT'
o.update(state2,ch,10.5)
# Crash detector later proves the chicken did move materially before reset.
e=o.on_crash({'event_time':11.7,'reason':'confirmed_progress_reset','start_x':100.0,'max_x':230.0,'reset_x':100.0},11.7)
assert e is not None,e
assert e['outcome']=='failure' and e.get('weak_action_attribution') is True,e
assert e['attribution']=='crash_progress_fallback',e
assert abs(e['attribution_confidence']-.55)<1e-9,e
print('PASS v524 crash-progress fallback GREEN attribution')
