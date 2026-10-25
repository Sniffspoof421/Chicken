# V5.5.0 root-cause analysis

## Supplied V5.4.9 run

Duration: ~111 minutes.

Outcome tracker recorded:
- 213 GREEN signals
- 18 acted GREENs
- 5 GREEN successes
- 4 GREEN failures

The remaining four failures are not all the same type.

## Post-jump ownership defect

The main loop used the same `learning_chicken` object for both crash learning and GREEN outcome ownership. During motion ROI rewarm it intentionally set that object to `None`.

That meant the outcome tracker could not see the exact landing frames where:
- chicken reached the target lane,
- target ownership advanced,
- or a provisional landing remained stable.

The later reset then became the first visible terminal event and was blamed on the GREEN.

## Latest failure examples

Signal 129 is the clearest genuine failure pattern:
- GREEN opened on a verified gap
- chicken movement reached the lane region
- target ownership did not validate the landing before regression
- chicken reset shortly afterward

Signal 193 shows the opposite pathology:
- chicken reached ~630 px
- remained around ~629-633 px through repeated VERIFY LAND states
- remained there for well over two seconds
- a later reset was still recorded as a GREEN failure

That is too late to treat the original GREEN as an unresolved jump.

Signals 1 and 135 reach target-switch landing geometry and then reset roughly 0.3-0.35 s later. V5.5.0 intentionally does not immediately call these successes. Target switch creates a provisional landing and a short survival interval decides the result.

## New landing policy

Target switch + one-lane geometry:
  ACTIVE -> PROVISIONAL LANDING

Then:
- stable for >=0.30 s -> SUCCESS
- regression/reset before survival -> FAILURE

Non-target-switch landing still requires the existing ~0.30 s stable hold before provisional, plus the new 0.30 s survival interval.

## Source-feedback defect

All supplied GREEN outcomes are logged with the wrapper source `v5-safe-window`, while the physical opportunity is `verified-gap` / `dynamic-gap`.

The state at recorded failure signals still showed source failure ETA floor = 0, so the physical dynamic-gap gate was not learning the failure history that belonged to it.

V5.5.0 uses `timing_source` for source reliability/failure ETA memory.

To avoid another no-GREEN regression, a source ETA floor is not raised until two confirmed failures from that source exist.

## Policy migration

Because pre-550 GREEN failure memory can contain false post-landing negatives, policy 550 clears only GREEN-specific negative direct memory on first load. Successful outcomes and autonomous traffic/model learning are preserved.

## Regression tests

Passed:
- V5.5.0 causal landing survival + rewarm visibility + physical-source feedback
- V5.4.9 preserved GREEN profiles / degraded FPS
- V5.4.7 runtime recovery / click-vs-CV separation
- V5.4.6 delayed action attribution
- V5.4.5 centered GREEN
- V5.4.4 difficulty modes
- V5.3.9 physical verified override
- V5.3.8 causal one-jump/reframe
- V5.3.5 fullscreen reframe
