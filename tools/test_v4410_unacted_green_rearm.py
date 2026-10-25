from app.outcome import GreenJumpOutcomeTracker

o=GreenJumpOutcomeTracker({
    'post_green_action_grace_seconds':0.75,
    'late_observation_window_seconds':1.8,
    'unacted_green_rearm_seconds':6.0,
})
# Fresh system may show a signal.
assert o.green_display_allowed(10.0)
# Simulate a GREEN that ended without action and is pending attribution.
o.pending_signal={'end_ts':10.0}
assert not o.green_display_allowed(10.2)
# Expire it as unacted; display must remain locked even after pending is gone.
o._expire_signal(10.8)
assert o.pending_signal is None
assert not o.green_display_allowed(13.0)
assert not o.green_display_allowed(15.99)
assert o.green_display_allowed(16.01)
# An active GREEN may continue; guard is only for a *new* GREEN.
o.current_signal={'end_ts':16.01}
assert o.green_display_allowed(16.1)
print('V4.4.10 unacted GREEN rearm test passed')
