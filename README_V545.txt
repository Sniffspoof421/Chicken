Chicken Road 2 AI Live V5.4.5 - CENTERED GREEN / GO-NOW TIMING

Run: start_v545.bat

ROOT CAUSE FOUND IN V5.4.4 TELEMETRY
- 45 visible GREEN signal IDs were logged.
- 37/45 GREEN starts occurred immediately after a frame with raw risk >=90.
- 41/45 GREEN starts followed substantial target-lane motion.
- 38/45 opened with <0.20 s of confirmed current clear time.
- Median clear time at GREEN start was only ~0.14 s.

This means V5.4.4 was turning GREEN on the first clear-looking frame after a
passing car. That explains the user's observation: clicking immediately can
fail, while waiting a fraction of a second during the same GREEN can succeed.
The gap estimate was often valid, but GREEN began too early in the gap.

V5.4.5 CHANGES

1) GREEN NOW MEANS GO NOW
A verified busy->clear gap must pass a post-pass settling dwell before GREEN:
- EASY:    0.18 s
- NORMAL:  0.24 s
- HARD:    0.30 s
- EXTREME: 0.34 s

2) PASSING-TRACK TAIL GUARD
If a target-lane track is still alive, add extra tail-clear time:
- EASY/NORMAL: +0.10 s
- HARD:        +0.12 s
- EXTREME:     +0.14 s

3) CLEAR CLOCK IS AUTHORITATIVE
The gate uses the current raw-motion clear clock first. It does not max several
clear clocks, so a stale dwell cannot hide newly returned traffic motion.
If motion comes back, the clear clock resets and GREEN is cancelled/withheld.

4) LEASE REBALANCED AFTER SETTLING
The post-pass dwell itself consumes the dangerous early tail of the gap. To
avoid recreating V5.4.2's no-GREEN starvation, the strong-physical presentation
reserve after settling is:
- EASY:    0.18 s
- NORMAL:  0.22 s
- HARD:    0.26 s
- EXTREME: 0.30 s

This does not lower RiskEngine's required ETA, which still includes jump time,
safety, learned reaction budget and pipeline latency.

5) EXISTING PROTECTIONS PRESERVED
- V5.4.4 difficulty mode switching
- V5.4.2 anti-jitter jump ownership
- cycle-aware GREEN rearm
- early motion-rise GREEN cancellation
- causal GREEN outcome ownership
- one GREEN = one jump
- fullscreen 3-lane reframe handling
- session speed guard
- verified physical ML override

NEW TELEMETRY
safe_window_v545_*.csv and state CSV expose:
- v5_post_pass_settle_required
- v5_post_pass_clear_elapsed
- v5_post_pass_ready

MODEL FILES
Keep existing:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib
Do not delete them.
