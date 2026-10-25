# V5.5.15 changes and validation

## Scope

The supplied video and three V5.5.14 sessions showed 39 GREEN starts, seven
classified successes and seven UNKNOWN outcomes. The learned failure count
stayed 15 while successes grew 81 to 88. Some inputs during valid GREEN were
not linked to an attempt because the horizontal CV movement threshold was not
reached. Existing input_audit was a file-only observer, not an ownership input.

This build connects it to the state machine without changing normal GREEN
admission. It also implements the proposed unresolved-vehicle detector in
shadow/diagnostic mode. It does not claim to repair every physical crash.

## Active input-to-outcome path

The Windows observer queues the same press-edge records it writes to disk.
The main loop drains the queue before capture/scene updates. Only Space is
eligible for the new ownership path, matching the supplied gameplay controls.
Left mouse, Up and Right do not acquire ownership through this path.

Eligibility requires a current/pending cue with exact signal ID and target
switch generation, an input timestamp inside the recorded display deadline,
a processing age <=0.75s, a baseline chicken position within 10% of one lane,
and equal nonzero input/cue foreground window handles. This is foreground
consistency, not independent verification of a game's identity or acceptance
of the key. The prior observed-movement attribution path is retained.

An eligible input creates a tentative attempt at the input timestamp. The
original feature vector and cue context travel with it. It is initially weak
and ineligible for supervised feedback. Fresh detected movement confirms it:
forward movement at least the existing 18px action-start parameter, or vertical
departure >=6% of lane width while horizontally near the baseline. These smaller
movement checks apply only after eligible input, not to ordinary detector jitter.

Confirmed reset/crash after confirmed movement uses the existing one-jump
failure path. It reaches SafeWindow feedback with the original cue features.
Input without movement is UNKNOWN on crash; multiple Space presses before
resolution cancel attribution; explicit viewport invalidation emits an UNKNOWN
audit event rather than silently deleting the input attempt. Existing exact
landing checks and final-success irreversibility remain.

Limitations: missed inputs, foreground=0, focus changes, long processing stalls,
and expired cues are excluded from this new path. A reset that CrashDetector
never recognizes may still remain unknown. Synthetic scroll is not promoted
to failure merely because input exists. Input records are sampled observations,
not hardware timestamps or proof of what was physically painted on screen.
The Windows OS input calls were not run on Windows in this environment.

## Unresolved incoming vehicle detector: diagnostic mode

The detector identifies recently observed, vehicle-sized objects overlapping
the watched lane, still upstream of or overlapping the crossing, with unresolved
or suspicious direction. It expires evidence using the existing required
crossing horizon, plus the tracker's reset/expiry lifecycle. It ignores small
fragments, adjacent objects and objects whose rear was observed beyond the
crossing. It invents no speed for singleton tracks.

Using h=160, a 440px lane offset and a 1.43s horizon, an approximate replay of
the 39 supplied GREEN starts would veto 32. This is not a full pixel replay,
and it includes successful historical cues. Enforcing that candidate would
risk the GREEN starvation the user explicitly asked us to avoid. Therefore
main.py invokes apply_unresolved_guard with enforcement disabled. The fields
upstream_unresolved_vehicle, upstream_uncertainty_would_block and
upstream_uncertainty_enforced are included in signal audit events.

The first video crash's recorded large fragment (track 612) triggers this
candidate, and expires after the bound. That demonstrates candidate coverage,
not a validated live safety improvement. Existing measured-trajectory prediction
continues using the earliest arrival across all incoming tracks. A regression
checks that a faster following vehicle wins over a slower earlier vehicle.

The next step is to distinguish actually departed silhouettes from lost
incoming silhouettes using independent visual evidence, and validate how that
candidate changes both opportunity rate and outcomes before enforcing it.

## What remains unverified

No software change here establishes that visible traffic determines this casino
game's outcomes. The in-game rules/fairness mechanism must be checked before
claiming that timing or traffic history can predict success. Unseen future
arrivals are also not recoverable from a tracker that never observed them.
The new feedback path cannot make independent random outcomes predictable.

No automatic relabelling of old UNKNOWN outcomes or historical model reset is
performed. Config.json is byte-identical to V5.5.14. The ordinary traffic/gap
learners, ROI recovery, observation timing fix, slow-profile logic and final
landing rules are preserved. This build does not extend GREEN display time.

## Validation

All 19 scripts pass: the 17 earlier regression scripts, new ownership/uncertainty
regressions, and an actual App.tick input-queue test. The new tests verify:

- eligible Space plus early movement plus confirmed reset produces failure;
- the actual SafeWindow predictor increments its failure-feedback count;
- click-only crashes stay UNKNOWN;
- late/mouse/wrong-cue/wrong-target/focus-changed inputs cannot arm ownership;
- additional inputs and camera invalidation remain UNKNOWN;
- a second on_crash call cannot relabel the resolved attempt;
- the recorded uncertainty fragment is detected and expires;
- diagnostic mode preserves admission and explicit enforcement blocks;
- earliest arrival is selected among two vehicles;
- App.tick consumes queued input before geometry processing and confirms movement.

These tests establish implementation behavior, not a live success percentage.
