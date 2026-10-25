# V5.4.4 root-cause analysis — difficulty/regime switching

## What the V5.4.3 telemetry shows

Run duration: about 63.2 minutes.

Observed:
- 15 GREEN signal IDs
- 1 acted GREEN
- 1 causally resolved outcome, which was a success
- 0 causally recorded GREEN failures
- only 23 CLEAR state frames

The perceived GREEN crashes were later resets several seconds after short GREEN
windows and were not owned by the GREEN outcome tracker. The larger problem in
this run is starvation/sticking, not a new causal-failure-label bug.

There was a particularly clear starvation interval from approximately minute 35
to minute 60 with zero V5 GREEN decisions. In that interval the dominant
SafeWindow blockers were LIVE GAP UNVERIFIED, FORECAST ETA and PHYSICAL ETA.

## Root cause 1 — adaptive regime state was not stable

`regime_samples` had median 0. The dominant regime reason was
`traffic_pause/refresh`. A traffic pause was creating a new regime even though a
pause by itself does not mean the speed/headway distribution changed.

This made the adaptive regime ID/samples poor authority for game hardness.

## Root cause 2 — the actual gap predictor resisted difficulty changes

While the regime layer reset too often, dynamic-gap prediction did the opposite:
it was too sticky.

V5.4.3 blended completed gap evidence as:

    65% long history + 35% recent history

and limited recent improvement to at most 1.12x the long-history lower bound.
So after a difficult section, the model could remain pessimistic through a later
easier section for many traffic cycles.

## Root cause 3 — one global historical-P25 rule is wrong across hardness modes

V5.4.3 strong physical override expected roughly `motion_gap_p25 >= 2.20 s`.
That can make sense in generous traffic, but in HARD/EXTREME traffic the normal
historical P25 is necessarily shorter. A rare current 2+ second verified gap was
therefore judged using the wrong distribution-level criterion.

The correct safety tradeoff is mode dependent:
- easy traffic: historical gap distribution can carry more authority;
- hard traffic: require stronger CURRENT gap confidence, lease and live motion
  cleanliness, but do not demand an easy-mode historical P25.

## V5.4.4

### Hysteretic EASY / NORMAL / HARD / EXTREME controller

Inputs:
- live motion gap P25 (recent preferred)
- live speed difficulty
- live density/busy fraction
- gap volatility

The score is EMA-smoothed. Hardening uses a shorter dwell; easing uses a longer
dwell. Stateful hysteresis prevents mode flapping around boundaries.

### Traffic pauses

Traffic pauses no longer create a new adaptive regime. Only statistical
speed/headway distribution changes do.

### Dynamic-gap prediction

Quantile, minimum support, confidence and maximum early-gap age are mode aware.
Recent-vs-long gap blending is asymmetric:
- a verified hardening trend moves conservative quickly;
- an easing trend may rise decisively only after the mode controller confirms it.

### SafeWindow mode profiles

Strong verified gaps use mode-specific current evidence. Historical P25 floor
falls as mode gets harder, while current confidence/lease and instantaneous
raw/motion/MOG safety become stricter.

HARD and EXTREME disable sustained observed-clear admission and require verified
busy->clear evidence.

## Regression verification

Passed:
- V5.4.4 hysteretic difficulty mode + mode-aware gap profile test
- V5.4.3 adaptive verified-gap lease regression
- V5.4.1 session-speed guard / target handoff
- V5.3.9 verified physical override
- V5.3.8 causal outcome / one-jump ownership
- V5.3.7 verified-gap fast path
- V5.3.5 fullscreen reframe
- V5.3.4 current-session speed authority
- V5.3.3 chicken-anchor geometry

The V5.4.2 fixed universal-lease expectation is intentionally not the governing
policy anymore; V5.4.3 already replaced it with adaptive verified-gap leases.
