# V5.5.10 investigation

Source: state/session/safe-window/GREEN outcome and JSONL audits from the
2026-10-22 05:21:11 run. State log spans approximately 9.75 minutes. There are
11 GREEN starts, five logged owned outcomes, and all five were marked success.
The state CSV has zero crash_event rows. That is an instrumentation result,
not evidence that no physical crashes happened.

## What was wrong

| Signal | Recorded evidence | Diagnosis |
|---|---|---|
| 4 | x~192 -> 649/y~767 -> 642/y~781, then x~191/y~732 | SUCCESS_FINAL was emitted before a settled landing; the next regression could no longer resolve the attempt. |
| 7 | x~192 -> 622/y~711 -> held 632/y~760 -> x~189/y~731 | Another early SUCCESS_FINAL; held/displaced sprite evidence was not a completed landing. |
| 5, 6, 9 | Success inferred from a backward screen-coordinate change plus target switch/VIEW_SCROLL | Geometry-derived VIEW_SCROLL is circular evidence. These are ambiguous without an independent observed landing. Signal 6 also has displaced y~784 immediately before the backward shift. |
| 8 | GREEN start followed by scene/viewport activity and a large backward coordinate change, with no action/unacted/outcome audit | Viewport cancellation silently discarded the unacted signal and therefore its audit trail. Physical result cannot be assigned confidently from these files. |

Do not report five out of five as physical accuracy. Coordinate replays for 4
and 7 reproduce regression outcomes with the corrected validator, but these
are not video ground truth or precise input-time attribution. Manual actions
without a causally observed GREEN attempt remain excluded from failure labels.

The upstream predictor was unavailable at all 11 GREEN starts. Current mature
tracks are required by the previous guard; fast cars can be in flight before a
third observation establishes direction. The patch admits a *veto only* from
two fresh same-lane measurements with positive displacement and limited lateral
movement. It never manufactures a clear forecast, SAFE example, or GREEN from
absence of a track. Detection gaps and unseen vehicles remain limitations.

## Implementation

The landing validator now requires fresh continuous measurements within 4% of
one lane spacing of pre-jump ground y, plus the existing success_hold interval
and stable_dx. Exact ownership/one-lane geometry remain required for finality.
The same evidence guard covers the ordinary provisional and manual-success
bridge paths. Once actually finalized, later viewport events cannot rewrite it.

Synthetic scroll handoffs still retain short provisional ownership and UI
rearm behavior, but stable coordinates alone resolve UNKNOWN, never SAFE.
Viewport cancellation queues an explicit UNKNOWN audit event. No unrelated
manual reset is relabelled a GREEN failure.

config.json is byte-identical to V5.5.9. Global ETA, probability, lease,
cooldown and difficulty thresholds, and slow-profile/model persistence code,
are unchanged. Existing trained weights are retained, including any historical
mislabels; those cannot be selectively removed from incremental weights using
these outcome CSVs alone.

## Validation

- Replayed recorded coordinate sequences for signals 4 and 7: no premature
  success, regression remains resolvable.
- New targeted tests: displaced-y landing, missing frame, real settled landing,
  finality after reset, ambiguous scroll UNKNOWN, viewport cancellation audit,
  and two-observation incoming traffic with negative controls.
- Existing landing/upstream and scroll-handoff tests updated to assert corrected
  evidence requirements, rather than the old immediate/coordinate-only success.
- Full App.tick tests: first and second jump, third-lane reframe, exception
  recovery, 68 simulated seconds missing chicken, lost grid, and reacquisition.
- Existing slow-profile/slow-geometry, threat-tail, gap-prior, display-expiry,
  Qt expiry callback, missed-GREEN rearm and learning/persistence checks.

No live patched gameplay or video replay has been performed. These changes
fix demonstrated bookkeeping/learning errors and an early trajectory blind
spot; they do not establish a new live success percentage.
