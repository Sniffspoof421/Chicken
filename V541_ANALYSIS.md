# V5.4.1 investigation and fix

## V5.4.0 outcome summary

Resolved acted GREEN outcomes:
- signal 125: success
- signal 261: failure
- signal 263: success

Signal 261 was a genuine one-lane reset, not a fullscreen reframe or old false
outcome attribution.

## Why signal 261 failed

Signal 261 was admitted by the V5.4.0 sustained observed-clear override at about
1.43 s ETA. The action was first detected about 1.59 s after GREEN began.

Immediately before the action, target-lane motion jumped from essentially zero
to a dangerous state:
- raw risk: 95
- motion corridor ratio: ~0.546
- MOG ratio: ~0.246
- frame-difference motion: ~0.220

The object tracker still had no incoming track, so this was an untracked fast
vehicle entering the lane.

## Speed-reference failure

At signal 261:
- clear-zone speed reference: ~392 px/s
- unique live crossing evidence in the short rolling window was sparse
- the same current game had already produced many faster confirmed crossings

From the supplied event log, before signal 261 there were 75 crossing events.
Using valid +Y forward speeds in the 80-945 px/s range, the current-session P80
was about 732 px/s.

The rolling speed authority had forgotten this because the game had a long quiet
period. Therefore the ~1.43 s observed-clear ETA was materially optimistic.

## V5.4.1 architecture

### A. Session-fast observed-clear guard
OnlineLearner records the process start timestamp and exposes only events created
during the current app session. RiskEngine derives a robust session forward-speed
guard after >=12 valid crossings:
- percentile: P80
- margin: 1.02
- max guard: 800 px/s

This does not replace the normal CZN speed reference. It is a separate
conservative speed authority used only for untracked observed-clear permission.

SafeWindow computes:

    observed_clear_policy_eta =
        effective_eta * czn_speed_reference / session_fast_guard

when the session guard is faster than the short-window reference.

Verified dynamic-gap timing is not changed.

### B. Sustained observed-clear is no longer a 1.40 s shortcut
New minimums:
- guarded ETA >= 1.62 s
- gap support >= 36
- gap P25 >= 1.75 s
- live clear elapsed >= 1.10 s
- heuristic probability >= 0.92
- raw risk <= 12
- motion corridor <= 0.025
- MOG <= 0.035

Strong observed-clear may bypass collapsed ML but cannot lower the physical ETA.

### C. Successful jump handoff uses target ownership, not text reason
The two successful V5.4.0 outcomes showed target_lane_switches advancing at
landing while target_lane_lock_reason was HOLD_SAME.

The real signal-261 failure reached the next-lane X region but target ownership
did not advance there.

V5.4.1 therefore closes a success when:
- target switch counter advanced since GREEN,
- viewport did not rebase,
- chicken is near the old signal-time target,
- displacement is one lane.

This is more reliable than requiring the literal ARRIVED string and prevents
successful jumps from remaining JUMPING for several seconds.

## Regression tests

Passed:
- V5.4.1 session-fast observed-clear guard + safe target-switch handoff
- V5.3.9 verified physical override
- V5.3.8 causal outcome/reframe
- V5.3.7 verified-gap fast path
- V5.3.6 GREEN reliability
- V5.3.5 fullscreen reframe
- V5.3.4 current-session CZN authority
- V5.3.3 chicken-anchor geometry
- V5.3.2 recent adaptation
- V5.3.1 progression
- V5.3.0 target advancement
- V5.2.9 one-jump outcome geometry

The old V5.4.0 regression that explicitly required a 1.42 s sustained observed
clear to become GREEN is intentionally superseded by V5.4.1 because that exact
policy produced signal 261's real crash.
