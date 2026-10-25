# V5.5.12 investigation

## Evidence from the latest supplied V5.5.11 run

Files: state, green outcomes, green failures and crashes dated
20261023_022441(1), plus signal_audit_v558(4) and outcome_audit_v555(7).
The older audit version names are retained by the application.

- Recorded state span: 41.58 minutes, 7,791 state rows.
- 16 GREEN starts, approximately 0.385 per minute.
- CROSSING ROI INCOMPLETE: 3,448 state rows (44.3%).
- Longest continuous incomplete-crop spans: 435.95 seconds and 416.84
  seconds; another lasted 146.03 seconds. These were predominantly resting
  chicken positions around y=730, rather than ongoing jumps.
- Zero logged tick exceptions. This run's apparent stuck state is not the
  previous TRACK ERROR exception path.
- Gap forecast latching reduced the unlatched bound in 445 of 7,467 rows
  with both bounds. This does not measure lost GREEN opportunities; the
  latch is retained because the crop failure is directly reproducible.

## Reproduced root cause and narrow repair

The original ROI builder chose its bottom from current chicken y + 145px.
It rebuilt for target ID, frame size or sufficiently large horizontal drift,
but never repaired lost vertical coverage. A crop selected at airborne
cy=679 ends at y=824. At resting cy=731, chicken h=160, the crossing check
needs coverage through ceil(731 + 58 + 160*.31) = 839. The crossing guard
correctly rejects the missing pixels; the crop builder never supplied them.

The integration regression seeds exactly that crop in the actual App.tick
path. V5.5.11 leaves its bottom at 824 and fails. V5.5.12 expands the crop,
warms its motion background, reports the empty crossing as available/clear,
and performs no further crop resets during 40 resting-jitter ticks.

The crossing rectangle calculation is now shared by capture planning and
occupancy checking. On stable scenes, the existing vertical crop expands
when it cannot contain this rectangle. It retains the original below-chicken
padding and does not shrink during settling. Existing horizontal recentering
and warmup behavior remain. Impossible offscreen coverage remains blocked;
an unchanged clipped crop does not repeatedly reset tracking.

## What the crash logs establish, and what they do not

The outcome log has five classified successes and two classified failures
(signals 1 and 16), all marked training eligible. Four more signals have
UNKNOWN viewport outcomes without an observed action. Five reset events
exist overall. Resets without an owned GREEN action are excluded from a
GREEN failure calculation; they cannot all be identified as deliberate
manual crashes from these files alone.

The five of seven classified result (71.4%) is a bookkeeping statistic,
not a verified physical success rate for clicks made during visible GREEN.
It must not be used to dismiss the user's report of roughly 90% failures.
There are no actual input timestamps or frame recordings in these logs.

For failure 1, GREEN ended at 1792702533.6577; large CV displacement was
confirmed at 1792702535.2632. For failure 16, these times were
1792704972.3882 and 1792704974.3009. Small displacement appears earlier in
both traces. Confirmation delay is not click delay, and the post-GREEN
causal grace is not proof the click happened inside the displayed lease.
No claim is made that the user reacted late, or that a specific vehicle
caused either reset. The new patch does not rewrite these failures as wins.

The rare-signal regression has a reproduced code cause. The physical cause
of every crash remains unresolved. Validating crash reduction requires a
new live run, ideally with a synchronized recording showing input and cue.
No further prediction thresholds are tightened on this incomplete evidence.

## Preserved behavior and verification

config.json is byte-identical to V5.5.11. Risk admission, gap forecasts,
outcomes, target-lane tracking, chicken detection, slow learning, missed
signal rearm, checkpointing and model files are not changed. safe_window.py
changes only its diagnostic filename version. No old weights are bundled.

The regression suite checks crossing occupancy and forecast invariants,
slow profiles, threat-tail maturity, degraded frame-rate headroom, landing
ownership, display expiry, actual first/second jump handling, viewport
reframing, tracking loss recovery, missed GREEN rearm and settled landing.
The new application-level test also demonstrates the old defect fails and
the patched implementation recovers without repeated warmup resets.
These checks establish software behavior, not live gameplay accuracy.

Validation result: all 14 existing scripts passed; the new ROI integration
script passed (15 total). Running the new test against V5.5.11 failed at
the expected crop-bottom assertion.
