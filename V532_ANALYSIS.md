# V5.3.2 analysis — current-session adaptation

Latest V5.3.1 run analysed: `state_20261012_220802.csv`, `safe_window_v531_20261012_220802.csv`, session/events/crash/outcome logs.

## What actually failed

- Run length: ~31.5 min.
- Only 4 visible GREEN episodes were captured in state telemetry.
- Long-term SafeWindow model entered the run with ~58,162 retrospective samples and ended near 58,720.
- Direct GREEN feedback was only ~6 successes / 6 failures, so causal user feedback was tiny relative to historical retrospective labels.
- During minutes 20–25 there were 136 states where every V5 hard safety veto passed. Their physical heuristic reconstructed at ~0.92 median SAFE, but the accumulated long-term model was effectively ~0.28 median. The old V5.3.1 blend therefore fell to ~0.44 median and produced zero GREEN.
- This proves the quality regression was not lack of data; stale cross-session data had too much decision authority for a game whose traffic regime changes.

## Failed GREEN discriminator

The V5.3.1 failed GREEN (signal 4) was an `observed-clear` signal with:
- ETA ~1.09 s
- current CZN confirmed events = 0
- motion gap P25 ~1.40 s
- no active track at signal time

Later blocked hard-safe states commonly had:
- ETA ~1.09–1.10 s
- motion gap P25 ~1.85 s
- motion gap support ~48–49
- clear corridor / MOG 0

V5.3.2 therefore does NOT simply lower the threshold. An observed-clear physical override now requires either current CZN confirmation or a strong lower-tail gap history.

## V5.3.2 changes

1. Two-timescale learning:
   - persisted model = long-term prior;
   - new session-local SGD starts fresh every launch;
   - constant learning rate keeps later-session evidence influential;
   - before local support: 60% physical heuristic / 40% long-term prior;
   - after local support matures: up to 60% current-session model, 25% physical heuristic, 15% long-term prior.

2. Evidence-qualified observed-clear override:
   - current clear maturity still required;
   - ETA still must meet V5 hardcore requirement;
   - hard vehicle/MOG/target/slow/follower/crash vetoes unchanged;
   - plus either >=2 current CZN confirmations OR motion-gap P25 >=1.55 s with >=12 samples;
   - minimum combined probability sanity floor = 0.55;
   - ETA margin reduced from +0.05 s to +0.01 s only after the stronger evidence check.

3. New telemetry:
   - `v5_heuristic_probability`
   - `v5_longterm_probability`
   - `v5_session_probability`
   - `v5_session_train_n`
   - `v5_session_train_safe`
   - `v5_session_train_unsafe`

## Offline replay sanity check

Using the V5.3.1 telemetry and reconstructing the physical heuristic:
- minutes 20–25 hard-safe rows: 136;
- median physical heuristic: ~0.92;
- inferred long-term model probability: ~0.28;
- V5.3.2 pre-session blend: ~0.66 median;
- 110 of those rows satisfy the new strong observed-clear evidence rule;
- they group into roughly 8 sustained candidate windows before downstream re-arm/action logic.

This is an offline diagnostic, not a promise of 8 displayed GREENs.

## Processing note

The final ~1–2 min of the run dropped from ~6.5 FPS to ~2.3 FPS, with capture/chicken/risk costs all rising. V5 correctly blocked on `PROCESSING`. V5.3.2 does not weaken this safety veto.
