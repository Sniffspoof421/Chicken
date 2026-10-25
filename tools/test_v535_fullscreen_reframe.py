from app.scene_motion import FullscreenProgressReframeGate
from app.outcome import GreenJumpOutcomeTracker

cfg={
    'fullscreen_progress_reframe_mode': True,
    'fullscreen_reframe_min_shift_lanes': 1.55,
    'fullscreen_reframe_max_shift_lanes': 2.45,
    'fullscreen_reframe_first_lane_max_x_ratio': .18,
    'fullscreen_reframe_cooldown_seconds': 1.0,
    'fullscreen_reframe_settle_seconds': .24,
}

# Fullscreen 2560-wide geometry: visible lane centres are about
# 190 -> 630 -> 1070. A normal lane-2 death to lane 1 is NOT a reframe.
g=FullscreenProgressReframeGate(cfg)
assert not g.update({'cx':190},440,2560,0.0)['detected']
assert not g.update({'cx':630},440,2560,1.0)['detected']
normal_reset=g.update({'cx':190},440,2560,2.0)
assert not normal_reset['detected'], normal_reset

# Third-lane completion is the game's deterministic cut: ~1070 -> ~190,
# i.e. two lane spacings back to the first visible lane.
g=FullscreenProgressReframeGate(cfg)
g.update({'cx':190},440,2560,0.0)
g.update({'cx':630},440,2560,1.0)
g.update({'cx':1070},440,2560,2.0)
cut=g.update({'cx':190},440,2560,3.0)
assert cut['detected'], cut
assert 1.9 <= cut['shift_lanes'] <= 2.1, cut
assert -900 <= cut['dx'] <= -850, cut
assert cut['count']==1, cut

# A huge detector teleport must not masquerade as the two-lane game cut.
g=FullscreenProgressReframeGate(cfg)
g.update({'cx':190},440,2560,0.0)
g.update({'cx':1950},440,2560,1.0)
tele=g.update({'cx':190},440,2560,2.0)
assert not tele['detected'], tele

# Outcome coordinates must survive the cut.  A GREEN action that began on lane
# 2 and reached lane 3 is still a one-lane success after the screen shifts two
# lanes left; it must not become jump_regression_reset.
o=GreenJumpOutcomeTracker({
    'expected_jump_px':440,
    'jump_min_ratio':.68,
    'jump_max_ratio':1.34,
    'chain_ratio':1.55,
    'success_hold_seconds':.10,
    'success_grace_seconds':.10,
    'landing_regression_px':85,
    'outcome_timeout_seconds':3.0,
    'stable_dx_px':14,
})
o.active_attempt={
    'signal_id':4,
    'baseline_x':630.0,
    'action_start_x':680.0,
    'action_start_ts':1.0,
    'expected_jump_px':440.0,
    'last_x':1070.0,
    'max_x':1070.0,
    'stable_since':None,
}
# Game cuts 1070 -> 190, so all old screen coordinates shift -880.
o.rebase_viewport(-880.0)
e1=o._attempt_progress({'cx':190.0},2.0)
assert not any(e.get('outcome')=='failure' for e in e1), e1
# Stable landing progresses to provisional then success.
e2=o._attempt_progress({'cx':190.0},2.12)
assert any(e.get('kind')=='provisional_landing' for e in e2), e2
e3=o._provisional_progress({'cx':190.0},2.24)
assert any(e.get('outcome')=='success' for e in e3), e3

print('PASS V5.3.5 fullscreen reframe gate + GREEN outcome rebase')
