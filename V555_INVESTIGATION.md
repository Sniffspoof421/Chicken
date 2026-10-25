# V5.5.4 run investigation and V5.5.5 changes

Sources: all seven supplied CSVs dated 20261021_220002. Analysis is read-only;
original records have not been edited. No screen recording or click log was
provided. Signals and outcome timestamps are logged observations, not proof
of exact physical action time.

## What the run records

- State trace duration: 27.653 minutes, 5,071 sampled state rows.
- GREEN counter reached 18. There are 26 sampled CLEAR rows (not 26 signals).
- Outcome CSV: eight successes, one failure. This is not a complete denominator
  for all GREENs, and no physical success percentage is claimed.
- Two successes carry SUCCESS_FINAL / target_switch_advance. Four other
  successes use synthetic progress-scroll handoff. Two use ordinary landing
  validation. The inferred handoffs warrant more caution than directly seen
  movement.
- Crash CSV contains seven reset detections. Six have no corresponding GREEN
  failure. For example, later resets follow signal 5 and 7 after their outcomes
  were already closed and with WAIT/ETA HOLD states during the later moves.
  They cannot simply be counted as seven causally owned GREEN failures.

## Signal 14: confirmed chronology defect

| Event | Unix timestamp |
|---|---:|
| GREEN begins | 1792601396.3559024 |
| GREEN last recorded end | 1792601396.8935552 |
| First reset frame (later confirmed) | 1792601398.868034 |
| Synthetic scroll action start | 1792601399.0170162 |

The attributed crash occurs 0.1489822 seconds BEFORE its inferred action.
CrashDetector requires multiple reset frames, but emits the timestamp of the
FIRST frame. During that confirmation interval the old progress-handoff logic
can construct a new provisional attempt from the reset/reanchor. When the
reset is confirmed, on_crash attaches it to that newer attempt without checking
chronology. This is a reproducible software defect. The learner already marked
this record training_eligible=0 / late_outside_causal_window, but it still
appeared as a GREEN failure in outcome counters.

This does not demonstrate that the physical jump was safe, nor that the user
clicked late. CV action confirmation is delayed and the action timestamp here
is synthetic. The physical cause of the reset remains unresolved.

V555 blocks synthetic handoff while a reset candidate is pending or confirmed
this tick. Independently, a reset timestamp earlier than the currently owned
action resolves UNKNOWN with reset_precedes_action and cannot train either
success or failure. outcome_audit_v555.jsonl preserves that exclusion.

## Presentation can outlive the remaining action lease

There are CLEAR samples with action lease 0.002242 seconds (signal 5) and
0.031864 seconds (signal 18). Signal 14 has 0.507402 seconds at its first sampled
CLEAR and 0.128875 seconds at its later sampled CLEAR. Processing rate around
signal 14 is approximately 6.5 FPS. The prior UI simply repainted on analysis
ticks and had no independent action-lease expiry. The lamp could therefore
remain GREEN between updates after the physical permission expired. State CSV
is sampled, so these rows do not measure exact stale-display duration.

V555 derives a deadline from the EXISTING verified-gap action lease, expires
presentation with a precise Qt timer, checks the deadline again during paint,
and checks it before admission and final display/logging. A continuing offer
may shorten its deadline but cannot roll it forward for the same target/gap.
The timer also closes the visible signal at the deadline rather than the later
analysis observation time. No minimum lease has been raised.

Qt shares the analysis event loop: a blocking tick can still delay repaint.
The paint-time guard prevents an expired state being painted again once the
loop resumes. This is a reduction of stale presentation, not a hard real-time
guarantee or a claim that this caused signal 14's physical collision.

## Upstream prediction coverage is limited

Usable upstream prediction is available in 302 state rows; 299 are blocked by
its arrival guard. None of the 26 sampled CLEAR rows has a usable upstream
prediction. Thus the guard is active, but it did not certify the future traffic
at the sampled GREEN instants. Blank prediction is unavailable evidence, not
infinite safe arrival.

For signal 14, sampled GREEN is already off at 1792601397.160217. A subsequent
row at 1792601397.858614 has predicted arrival 0.131984 seconds, followed by
0.0 seconds at 1792601398.191212. The raw session rows are decimated and lack
all direction/fit eligibility fields, so they cannot establish whether an
incoming vehicle was visible but undetected earlier. Raising global ETA or
confidence floors is not justified by these records. The V554 trajectory guard
is retained; no claim is made that V555 solves unseen/undetected traffic.

## Preserved and tested

config.json is byte-for-byte unchanged from V554. No ETA, support, probability,
lease, cooldown, difficulty or admission setting has been changed. The core
predictor, final landing lock, valid scroll handoff, autonomous traffic learning
and supplemental manual-success weights are retained. No model data is bundled.

Passed: V551 convoy-tail, V552 degraded-FPS/scroll handoff/timing isolation,
V553 prior/rearm/CSV schema, V554 final landing/upstream, new V555 chronology,
reset-candidate and lease tests, supplied signal-14 log replay, actual Qt expiry
callback test, Python compilation. The older V549 lease assertion was already
known to fail in the supplied V553/V554 lineage. V550's provisional target
handoff expectations were explicitly superseded by V554. Live gameplay and
Windows desktop capture were not tested here.

## Running the update

Extract the ZIP to a new folder. Copy your prior data/model folder to retain
learning, then launch start_v555.bat using the same Python installation.
Retain the prior build as a backup. New logging includes decision frame time,
display deadline/expiry, pending-reset flags and an outcome audit JSONL.
For the next test, retain these logs and a screen recording showing both game
and widget. A click-event trace is needed to distinguish click timing from CV
movement-confirmation delay.
