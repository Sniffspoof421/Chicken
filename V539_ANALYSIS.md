# V5.3.9 analysis — restore verified opportunities without weakening hard safety

## Latest V5.3.8 run

Run duration: about 96.6 minutes.

V5.3.8 did not have a perception/target deadlock. Traffic learning was active and the verified-gap pipeline continued to produce physically valid windows. The starvation moved to the final learned probability gate.

Key telemetry:
- SafeWindow evaluations: 42,491.
- V5 decisions: 439 frames.
- Visible CLEAR frames in state telemetry: 78.
- Internal GREEN signals: 52; visible signal IDs: 48.
- Hard-safe verified-gap frames: 693 across 236 dynamic-gap cycles.
- 128 of those verified cycles never produced a V5 decision.

The strongest failure appears late in the run. From roughly minute 60 onward, verified physical opportunities still existed, but GREEN decisions dropped to zero. During the same period:
- physical heuristic on verified gaps remained roughly 0.88–0.94;
- blended SafeWindow probability collapsed to roughly 0.23;
- long-term probability often approached 0.00;
- session-model probability often approached 0.00.

The current-session learner ended with about 7,769 retrospective labels:
- SAFE: 2,963
- UNSAFE: 4,806

This caused a pathological disagreement: live busy→clear evidence said the target lane was physically actionable, while historical/session retrospective ML vetoed it.

## What V5.3.9 changes

V5.3.9 adds a **strong verified physical override**. It can override only the learned probability; it cannot override any hard safety gate.

A collapsed ML score may be bypassed only when ALL of the following are true:
- gap provenance is a live dynamic verified busy→clear gap;
- every existing hard veto has already passed;
- physical heuristic >= 0.91;
- dynamic-gap confidence >= 0.75;
- motion-gap support >= 12;
- motion-gap P25 >= 1.80 s;
- action lease >= max(existing FPS-aware lease requirement, 0.32 s);
- raw risk <= 18;
- motion corridor ratio <= 0.04;
- global MOG ratio <= 0.055.

Hard vetoes remain unchanged, including:
- visible vehicle;
- uncertain vehicle;
- target/anchor geometry failure;
- tracking rewarm / viewport instability;
- processing failure;
- slow-after / slow-approach guard;
- motion/MOG busy;
- insufficient physical ETA;
- insufficient action lease;
- repeated crash-memory hard veto;
- learned direct GREEN-failure hard similarity.

## What is deliberately NOT changed

The observed-clear / forecast path remains strict at 1.58 s. Earlier supplied runs showed that ~1.15–1.43 s unverified/observed-clear signals were unreliable. V5.3.9 does not restore that unsafe behavior.

The V5.3.8 causal outcome and fullscreen reframe fixes remain unchanged.

## Offline diagnosis of the latest run

The supplied run contains many examples where:
- effective ETA was around 2.0–2.8 s;
- motion gap history was >2 s;
- raw risk was ~11–12;
- no visible or uncertain vehicle existed;
- physical heuristic was ~0.92–0.96;
- yet blended ML probability was only ~0.23–0.30.

A conservative replay of the new rule identifies roughly 35–40 additional strong verified opportunities in the supplied telemetry that were previously rejected by ML. This is diagnostic only; actual displayed GREEN count still depends on one-jump/rearm and real-time hard hazards.

## Regression checks

Passed:
- V5.3.9 verified physical override + hard-veto preservation
- V5.3.8 causal GREEN attribution / recent-peak fullscreen reframe
- V5.3.7 verified-gap fast path
- V5.3.6 expired-GREEN attribution policy
- V5.3.5 fullscreen reframe outcome rebase
- V5.3.4 current-session CZN speed authority
- V5.3.3 chicken-authoritative target geometry
- V5.3.2 two-timescale adaptation
- V5.3.1 progress-scroll Hardcore logic
- V5.3.0 target advancement
- V5.2.9 one-jump outcome geometry

## Run

Use `start_v539.bat`.

Keep the existing trained model files:
- `data/models/online_state_v532.joblib`
- `data/models/safe_window_v532.joblib`

Do not delete them. V5.3.9 specifically prevents a collapsed learned prior from vetoing a strong live verified physical opportunity.
