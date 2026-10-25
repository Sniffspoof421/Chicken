# V5.2.3 analysis - sustained GREEN vs flicker GREEN

Source run: `state_20261010_203530.csv`, `safe_window_v522_20261010_203530.csv`,
`crashes_20261010_203530.csv`, `green_failures_20261010_203530.csv`, and
`green_outcomes_20261010_203530.csv`.

## What the run showed

There were 32 displayed GREEN episodes (51 CLEAR state rows).

Using display duration:
- **Flicker** (<0.45 s): 19 episodes, median ~0.321 s.
- **Sustained** (>=0.60 s): 12 episodes, median ~0.693 s.
- One intermediate episode: ~0.597 s.

The two formally attributed GREEN failures had signal durations:
- ~0.212 s
- ~0.142 s

Their actions began ~2.17 s and ~1.87 s after GREEN start. Both were transient
single-frame/near-single-frame V5 approvals, not mature sustained windows.

In this run no recorded crash occurred within 5 seconds of a sustained GREEN
episode. The one state-log GREEN followed by a crash within 5 seconds was in the
flicker group (~0.303 s).

Probability alone could not separate the groups:
- flicker median V5 probability ~0.924
- sustained median V5 probability ~0.941

Therefore simply increasing the probability threshold is not the right fix.

## V5.2.3 correction

V5.2.3 adds a sustained commit state machine:

1. Raw V5 safe decision begins a candidate timer.
2. Candidate must remain continuously valid for `0.40 + 0.12*difficulty` sec.
3. Any pre-commit probability dropout resets the timer.
4. Only after maturity is `v5_decision=True` exposed to the GREEN indicator.
5. Once committed, a small probability dropout can be bridged for <=0.42 s if:
   - every hard safety veto still passes;
   - probability remains within 0.035 of the threshold;
   - ETA remains >= absolute physical floor + 0.06 s.
6. Hard hazards cancel immediately; the commit latch never masks a real threat.
7. Lane/target/viewport context change resets the commit.

This targets the observed dangerous GREEN population directly: transient safe
pulses are converted to CHECKING rather than visual GREEN.
