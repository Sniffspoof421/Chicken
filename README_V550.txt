Chicken Road 2 AI Live V5.5.0
CAUSAL LANDING SURVIVAL + PHYSICAL-SOURCE FAILURE LEARNING

RUN
  start_v550.bat

IMPORTANT
V5.5.0 preserves V5.4.9 GREEN admission logic.
No new global GREEN threshold increase is introduced.

WHAT THE V5.4.9 RUN PROVED

Resolved acted GREEN outcomes:
  5 successes
  4 failures

The key problem was post-jump outcome ownership, not simply GREEN probability.

Failure examples showed three different patterns:
- one jump never achieved trusted target ownership before regression -> genuine failure
- some jumps reached target-switch/landing geometry but reset ~0.3 s later -> must remain provisional until brief survival is proven
- one jump remained stably landed for >2 s but was still later blamed as a GREEN failure because the 1.2 s post-landing validator lost chicken visibility during motion rewarm/runtime gaps

ROOT CAUSE 1 — OUTCOME TRACKER WAS BLIND DURING MOTION REWARM

Main loop created:
  learning_chicken = None
whenever motion ROI was rewarming.

That is correct for crash/traffic learning, but wrong for GREEN outcome ownership because the jump itself often causes the ROI rewarm. The target may advance while the outcome tracker receives no chicken.

V5.5.0 splits the two paths:
- crash/traffic learner keeps the conservative rewarm gate
- outcome tracker receives fresh chicken geometry whenever the coordinate frame itself is stable

ROOT CAUSE 2 — IMMEDIATE TARGET-SWITCH SUCCESS WAS TOO OPTIMISTIC, BUT THE OLD 1.2 s POST-LANDING WAIT WAS TOO SLOW

V5.5.0 uses a middle path:
- target ownership advance proves a provisional landing
- it is NOT immediate SUCCESS
- the chicken must survive a short 0.30 s post-landing interval
- regression/reset before that interval remains FAILURE
- stable landing past that interval becomes SUCCESS

The existing non-target-switch path already requires ~0.30 s stable position before entering provisional landing, so its total stable proof is roughly ~0.6 s rather than the old ~1.5 s.

This prevents a jump that lands and instantly dies from being called safe, while also preventing a later unrelated reset from being blamed on a clearly completed jump.

ROOT CAUSE 3 — FAILURE FEEDBACK WAS STORED UNDER THE WRONG SOURCE

The UI/outcome log labels GREEN as:
  eta_source = v5-safe-window

but the physical gate that authorized the opportunity is often:
  timing_source = dynamic-gap

V5.4.9 recorded failures under v5-safe-window, so dynamic-gap failure reliability/floors could remain unchanged.

V5.5.0 stores source-specific success/failure feedback under the physical timing source.

Protection against starvation:
- one failure does NOT raise the source ETA floor
- at least two confirmed failures from the same physical source are required

ROOT CAUSE 4 — PRE-550 FALSE GREEN-FAILURE MEMORY

Policy version is bumped to 550. On first load V5.5.0 automatically clears only:
- GREEN-specific failure counters
- GREEN failure ETA floors
- direct SafeWindow failure prototypes
- crash-memory entries whose source is acted_green_failure*

Preserved:
- validated GREEN successes
- traffic speed/type/gap learning
- long-term online model
- manual crash learning
- manual successful jump learning
- current-session traffic adaptation

Do NOT delete model files. The migration is automatic.

FAILURE WORDING

Post-GREEN movement confirmation is now described as:
  delayed_confirmation_failure

not:
  late_causal_failure

The logged movement-confirmation timestamp is not proof that the user clicked late.

PRESERVED FROM V5.4.9
- V5.4.7/V5.4.9 GREEN thresholds and mode profiles
- degraded-FPS operation
- centered post-pass GREEN
- EASY/NORMAL/HARD/EXTREME switching
- click-vs-CV timing separation
- unique manual-success learning
- runtime-gap recovery
- mid-lane chicken identity protection
- fullscreen progress reframe logic
- one GREEN = one jump

MODELS
Keep existing:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do NOT reset them.

LOG
  safe_window_v550_*.csv
