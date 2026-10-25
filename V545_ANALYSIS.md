# V5.4.5 investigation — GREEN was opening too early after a passing car

## What the V5.4.4 telemetry proved

The issue was not primarily that GREEN stayed too long or that the gap detector
was completely wrong. The important timing problem was at GREEN *entry*.

Across the supplied V5.4.4 run:
- 45 visible GREEN IDs were observed.
- 37/45 GREEN starts came immediately after a frame with raw risk >=90.
- 41/45 starts followed significant target-lane motion.
- 38/45 started before 0.20 s of confirmed current clear time.
- Median clear time at GREEN start was ~0.14 s.
- Median preceding busy duration was ~0.52 s.

A representative acted sequence was:
1. WAIT, raw risk 95, motion corridor ~0.43
2. WAIT, raw risk 95, motion corridor ~0.36
3. first apparently clear frame -> GREEN immediately
4. ~0.31 s later GREEN still visible
5. then GREEN ends as the gap margin collapses
6. target-lane motion surges again and the jump/reset follows

This matches the user's direct observation: jumping immediately on GREEN can
fail, while waiting briefly inside the same GREEN may succeed. The GREEN began
at the tail of the passing vehicle rather than at the actionable center of the
gap.

## V5.4.5 correction

### Mode-aware post-pass settling
Before a verified gap can display GREEN, current clear time must reach:
- EASY 0.18 s
- NORMAL 0.24 s
- HARD 0.30 s
- EXTREME 0.34 s

If a target-lane track is still alive, an additional tail-clear dwell is added:
- +0.10 s EASY/NORMAL
- +0.12 s HARD
- +0.14 s EXTREME

This uses `motion_current_clear_elapsed` as the authoritative clock. A stale
secondary clear clock cannot keep the gate open if current motion has returned.

### Why the strong physical lease is slightly smaller
The dynamic gap required ETA already includes jump time, safety, learned
reaction delay and measured pipeline latency. The new post-pass dwell consumes
the unsafe early part of the gap. Keeping the previous physical presentation
reserve unchanged would double-count safety and recreate GREEN starvation.

After settling, strong verified gaps use presentation reserves of:
- EASY 0.18 s
- NORMAL 0.22 s
- HARD 0.26 s
- EXTREME 0.30 s

Standard/ML-only verified-gap reserves remain unchanged.

### Offline replay indication
Using the supplied state stream, approximately 32 strong verified frames across
about 20 separated opportunities still survive the new post-pass timing rule.
This is deliberately lower than the 45 early-start GREEN IDs, because the
first-frame/tail-of-car signals are the class being removed. Standard high-ML
opportunities can add to that count at runtime.

## Regression results

Passed:
- V5.4.5 centered GREEN post-pass timing
- V5.4.5 track-tail timing
- V5.4.5 anti-jitter action ownership
- V5.4.5 cycle-aware rearm
- V5.4.4 difficulty-mode controller / mode-aware profiles
- V5.3.8 causal outcome ownership / recent-peak reframe
- V5.3.5 fullscreen reframe
- V5.3.4 current-session CZN authority
- V5.3.3 chicken-anchor geometry
- state CSV schema alignment (349 columns)

Older tests that explicitly require GREEN on the first ~0.18-0.20 s clear frame
are intentionally superseded by V5.4.5; the supplied V5.4.4 telemetry proves
that exact first-clear-frame behavior is the failure mode being corrected.
