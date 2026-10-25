# V5.2.2 analysis - 2026-10-10 GREEN failure run

## Latest run findings
- Runtime: ~1.21 hours.
- 27 logged GREEN episodes.
- 11 crash records.
- 7 manual failures learned.
- 4 GREEN failures were explicitly attributed to GREEN.
- 0 GREEN successes were recorded in this run.
- Safe-window learner ended with ~6,757 samples: 3,147 SAFE / 3,610 UNSAFE.

## Critical defect found
Every one of the four GREEN-attributed failures was written with:
`training_eligible = 0`
and:
`training_skip_reason = late_after_green_expired`

Their action delays from GREEN start were approximately:
- 1.705 s
- 2.347 s
- 1.415 s
- 1.263 s

The corresponding GREEN durations were only approximately:
- 0.619 s
- 0.576 s
- 0.144 s
- 0.926 s

The outcome tracker had already causally tied those jumps to the GREEN signal,
but OnlineLearner then discarded the failures because visible chicken motion
was detected after GREEN had disappeared. This prevented source-failure counts,
failure ETA learning and supervised outcome learning from updating.

Separately, SafeWindowPredictor never received the exact GREEN outcome at all.
It learned only from generic retrospective future-window labels, so its
probability could remain ~94-98% even after actual GREEN crashes.

## V5.2.2 correction
- Attributed late failures inside the causal window are now training eligible.
- The exact V5 decision feature vector is attached to the signal snapshot and
  trained directly from acted GREEN outcomes.
- GREEN failures enter a short-term decaying similarity memory for immediate
  suppression of near-identical repeats.
- Validated GREEN successes reduce nearby failure memory.
- Failed actions no longer train the reaction-delay budget.
- The four latest failed GREEN contexts are bundled as normalized failure
  prototypes in `data/models/v522_failure_seed.json`.

## Offline effect on the latest run
Using the seeded failure-memory layer against the 27 logged GREEN-start states,
6 would be suppressed by the conservative similarity/penalty layer, including
exact repeats of known failure contexts. The memory is intentionally local;
it does not globally disable GREEN.

## Regression results
Passed:
- V5.2.2 direct GREEN failure feedback + causal late learning
- V5.2.2 migration preservation/reset checks
- V5.2 identity + target-follow + asymmetric slow logic
- V5.2.1 live-gap and extended attribution
- V5.0.1 indicator handoff
- GREEN signal dedup
- unacted GREEN re-arm
- causal late GREEN failure learning
- dynamic-gap confirmation
- MOG veto
- live slow fallback + fast follower veto
- slow geometry guard
- immediate target geometry
- viewport rebase
