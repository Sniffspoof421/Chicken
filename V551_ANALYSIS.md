# V5.5.1 failure investigation

## V5.5.0 outcome summary

The supplied run resolved seven acted GREEN outcomes:
- 6 successes
- 1 failure

There were seven crash records overall, but the other crashes occurred roughly
22-63 seconds after the preceding GREEN or had no causal GREEN outcome. The only
confirmed causally linked GREEN failure is signal #19.

## Signal #19

At GREEN start the predictor reported approximately:
- effective/dynamic remaining ETA: 2.19 s
- dynamic-gap confidence: 0.97
- motion-gap support: 41
- motion-gap P25: 2.18 s
- action lease: 0.82 s

Those numbers normally look excellent.

But direct traffic evidence told a different story.

Immediately before GREEN:
- raw risk was ~98
- a visible threat was present
- three vehicle tracks remained

The first CLEAR state occurred only ~0.27 s after that direct high-risk/visible
threat. Roughly 0.26 s after GREEN, raw risk returned to ~98 and visible threat
returned.

Therefore the 2.19 s gap prediction was wrong for the current local sequence.
The model had opened on a transparent interval between adjacent vehicles rather
than a true mature traffic gap.

## Why the existing centered/post-pass guard missed it

The motion-clear clock was already about 0.44 s at GREEN onset. Motion segmentation
can become quiet before the direct visible-threat tracker considers the car fully
clear. Historical gap statistics then made the gap look highly confident.

The model had no independent requirement for time since the last DIRECT threat.

## Outcome classification

This failure is not evidence that the user clicked late.

After the GREEN, the chicken entered VERIFY LAND while lane risk was already
~95/90. The later reset was therefore consistent with a genuinely unsafe window.
V5.5.0's causal landing logic correctly did not convert this into a success.

## V5.5.1 policy

Add an independent recent-threat tail maturity gate:

    recent_threat_age >= 0.55 s

before a new verified-gap GREEN may start.

Hard reason while waiting:

    THREAT TAIL SETTLE

This does not alter ETA, action lease, ML probability, difficulty mode, dynamic
confidence, landing survival, or source feedback.

## Replay impact on supplied V5.5.0 run

There were 21 observed GREEN starts.

Using 0.55 s recent-threat maturity:
- signal #19 is blocked/delayed
- the other 20 observed GREEN starts are not blocked by this new condition

So this is a one-failure-specific correction rather than another global tightening.

## Regression tests

Passed:
- V5.5.1 threat-tail guard / mature-gap preservation
- V5.5.0 causal landing survival and physical-source feedback
- V5.4.9 preserved V5.4.7 GREEN logic
- V5.4.7 runtime recovery / click-vs-CV separation
- V5.4.5 centered GREEN timing / cycle rearm
- V5.4.4 difficulty modes
- V5.3.9 physical override
- V5.3.8 causal outcome / reframe
