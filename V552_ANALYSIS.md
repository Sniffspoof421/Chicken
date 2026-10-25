# V5.5.2 failure investigation

## Supplied V5.5.1 sessions

Session 20261015_231136:
- duration ~64.5 min
- 8 GREEN signals
- 0 acted GREENs
- 0 GREEN successes/failures
- 5 generic crash records
- only one crash occurred within 10 s of a GREEN: ~3.63 s after signal #3

Session 20261016_002001:
- duration ~6.75 min
- 4 GREEN signals
- 0 acted GREENs
- no crash occurred within ~23 s of a GREEN

Therefore V5.5.1's current telemetry does NOT show a new confirmed GREEN-outcome
failure label. Instead it shows an action-ownership blind spot.

## The suspicious V5.5.1 GREEN

Signal #3 in the long run:
- processing FPS ~2.3415
- mode NORMAL
- verified-gap confidence ~0.95
- dynamic remaining ~1.9919 s
- required ETA ~1.5133 s
- action lease ~0.4785 s
- selected physical lease requirement ~0.4671 s
- margin above requirement: only ~0.0114 s
- raw risk 2
- no recent direct threat

The signal therefore passed by roughly eleven milliseconds beyond the one-frame
degraded-FPS reserve. At ~2.34 FPS that is not a practically usable margin.

V5.5.2 adds +0.08 s ONLY to the degraded-FPS frame-margin branch. Normal-FPS
logic is unchanged.

Replay:
- long degraded run: marginal CLEAR rows are removed; the strongest low-FPS
  openings remain
- short ~6.4 FPS run: 10 of 11 observed CLEAR frames remain eligible by the
  lease rule, showing this is not a global tightening

## Hidden progress / zero acted GREEN

After signal #3:
- chicken is ~632 px at GREEN
- target ~1072 px, target switch counter 17
- intermediate chicken animation is not sampled
- ~3.14 s later chicken reappears near ~189 px
- target switch advances to 18
- target lock reason = VIEW_SCROLL

That sequence is positive game-progression evidence: a one-lane jump occurred
and the viewport scrolled, but low FPS missed the forward landing frames.

The normal action grace had already expired, so V5.5.1 left green_acted=0 and
could not learn the result.

V5.5.2 adds a narrowly constrained progress-handoff attribution:
- exact one target-switch advance
- VIEW_SCROLL or explicit progress reframe
- fresh chicken
- post-scroll chicken roughly one lane left of signal baseline
- <=4.0 s from signal end

This creates a provisional landing, not instant success. It must survive 0.75 s.
If a crash occurs during that survival window it is learned as a GREEN failure.

Importantly, crash geometry alone can never invoke this path.

## Preserved logic

Unchanged:
- V5.5.1 recent-threat tail >=0.55 s
- V5.5.0 provisional landing survival and physical-source feedback
- V5.4.9/V5.4.7 decision profiles and difficulty modes
- centered post-pass GO-NOW timing
- click-vs-CV reaction split
- causal one-GREEN/one-jump ownership
- third-lane/fullscreen reframe handling
- current-session speed authority
- ML physical verified-gap override

## Regression status

Passed:
- V5.5.2 degraded-FPS headroom / progress handoff / timing isolation
- V5.5.1 threat-tail guard
- V5.5.0 causal landing survival + source feedback
- V5.4.7 runtime recovery / click-vs-CV / mid-lane identity
- V5.4.6 delayed causal attribution
- V5.4.5 centered GREEN
- V5.4.4 difficulty modes
- V5.3.9 physical override
- V5.3.8 causal ownership/reframe
- V5.3.5 fullscreen reframe

The old V5.4.9 test that asserts the exact one-frame degraded lease margin is
intentionally superseded by V5.5.2: the current V5.5.1 failure is direct evidence
that an ~11 ms surplus over that rule is not actionable.
