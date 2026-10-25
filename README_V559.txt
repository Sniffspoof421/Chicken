V5.5.9 — directional slow learning with protected general behavior

RUN
Extract to a NEW folder. Copy the entire data folder from your working V558
installation into this new folder, then run start_v559.bat. Keep the old folder
as backup. Do not reset/retrain or overwrite newer local models with an older
snapshot. This ZIP contains code and documentation, not replacement weights.

FIXED SLOW-LEARNING INCONSISTENCY
Live slow-window geometry used forward_class, while historical slow-anchor
learning used class from total tracked speed. Your saved history contains 185
class disagreements among 1,069 retained vehicle events. A history entry can
therefore count as slow in one component and medium/fast in the other.

The slow-specific profile now uses stored forward_class, including follower
classification. Old records without forward_class retain their original class.
Existing history is read in place; nothing is deleted or relabeled on disk.
Recent evidence can adapt the profile once mature: >= the existing local
support minimum on the current lane, or twice that support across current
lanes. Both events must be in the current segment and last 180 seconds. Sparse
recent examples fall back to historical evidence. Reset boundaries are never
crossed; dangerous fast-follower examples are retained alongside safe examples.

PROTECTING WORKING LOGIC
The new profile is selected only around a live slow vehicle or a slow pass in
the last 2.5 seconds. Otherwise the original total-speed historical calculation
is retained. On all six lanes in the supplied model, those ordinary-traffic
profile outputs match V558 within 1e-12. config.json is byte-identical to V558.
GREEN/ETA/lease/probability/support and detector thresholds are unchanged.
Slow-before geometry, slow-after body clearance, follower ETA and fast-follower
vetoes remain in force. Landing locks, tracking recovery and missed-cue rearm
are preserved. This is not a global relaxation of GREEN admission.

LEARNING RETENTION
Your attached online snapshot trails the final live counters. That may simply
mean it was copied before shutdown; loss is not proven. The previous default
saved this learner on normal exit only. V559 requests an atomic checkpoint
about every 90 seconds, only during stable idle states with no active GREEN,
jump/rearm or pending V5 authorization. It freezes a coherent snapshot and
writes it on a background thread. A failed write preserves the prior model.
Normal shutdown waits for any outstanding checkpoint and saves the latest state.
No traffic learning depends on manual play. Manual successful-jump weights are
unchanged and remain supplemental.

LOGS
State adds slow profile source/current support/class-disagreement diagnostics,
slow follower ETA and model-checkpoint status/time/error. Signal action records
now include observation time, chicken coordinates, lane and target/cycle IDs.
Predictor logs use v559; runtime_errors_v559.log records unexpected errors.
Existing signal_audit_v558.jsonl and outcome_audit_v555.jsonl names are retained.

LIMITS
The supplied run has 15 registered cues and 4 attributed outcomes, all logged as
success (two directly observed target handoffs and two inferred scroll handoffs).
Its four recorded resets occur 44–51 seconds after the preceding cue, which the
audit marked unacted. These logs cannot establish the cause of your reported
later-lane GREEN crashes. This build fixes the demonstrated slow-profile defect
and improves retention/auditing; physical collision improvement is unverified.
Read V559_INVESTIGATION.md for evidence and tests.
