# Chicken Road 2 AI Live — Logic History / Do Not Revisit

This file is the decision record for V5.x. Before changing GREEN logic, check
this list so a previously disproven idea is not reintroduced.

## KEEP — proven or still required

| Version | Change | Result / decision |
|---|---|---|
| V5.0/V5.0.1 | SafeWindow probability replaced stacked soft ETA thresholds; old indicator stopped re-blocking V5 approval | KEEP. Foundation of current decision path. |
| V5.0.4 | Tracking recovery, false manual-success cleanup, reduced per-frame I/O, motion-clear lease | KEEP. Corrected stale/stuck state and I/O problems. |
| V5.3.3 | Chicken-authoritative lane phase + target sync | KEEP. Prevents stale target/lane geometry. |
| V5.3.4 | Current-session CZN speed authority + strong busy→clear motion bootstrap | KEEP. Historical fastest speed must not permanently pin ETA. |
| V5.3.5 | Fullscreen third-lane progress reframe | KEEP. Normal game screen cuts must not be learned as crashes. |
| V5.3.8 | Causal GREEN ownership; removed fabricated crash fallback; one GREEN owns one jump | KEEP ABSOLUTELY. Never restore crash→fake action attribution. |
| V5.3.9 | Strong live verified-gap physical override of stale/collapsed ML | KEEP. ML may not veto excellent current physics. |
| V5.4.4 | EASY/NORMAL/HARD/EXTREME hysteretic difficulty modes | KEEP. Hardening fast; easing slower. |
| V5.4.5 | Post-pass centered GREEN / GO-NOW timing | KEEP. Do not GREEN on first transient clear frame after a car. |
| V5.4.6/V5.4.7 | Separate user click budget from delayed CV movement confirmation; fast-traffic mode floor; runtime recovery/mid-lane identity guard | KEEP. CV action timestamp is not human reaction time. |
| V5.4.9 | Restore V5.4.7 GREEN profiles; allow safe degraded-FPS operation; unique manual success by target switch | KEEP, except the exact one-frame degraded lease margin is superseded by V5.5.2 below. |
| V5.5.0 | Fresh chicken visible to outcome tracker during motion rewarm; provisional landing survival; physical timing-source feedback | KEEP. Fixed false post-landing failures and source-learning mismatch. |
| V5.5.1 | Independent recent direct-threat tail maturity >=0.55 s | KEEP. Targeted the one confirmed convoy-tail failure without globally tightening ETA/ML. |
| V5.5.2 | Degraded-FPS extra lease headroom + positive progress-scroll GREEN ownership | KEEP pending live validation. Current logs directly justify both. |

## SUPERSEDED / DO NOT REINTRODUCE

| Version / idea | Why it failed |
|---|---|
| V5.3.7 legacy crash fallback | Fabricated actions from later crashes and turned unrelated resets/reframes into GREEN failures. Removed in V5.3.8. |
| V5.4.0 observed-clear ~1.40 s shortcut | Produced a genuine unsafe GREEN; signal margin was exhausted before usable action. Do not globally lower observed-clear ETA again. |
| V5.4.1 strict session-fast observed-clear policy as primary recovery | Over-corrected opportunities and still did not solve action ownership. Session speed guard is useful, but not as a blanket GREEN suppressor. |
| V5.4.2 flat +0.55 s verified action lease | Double-counted reaction time already inside dynamic required ETA and starved GREEN. Never add a second large global lease. |
| V5.4.8 global high lease floors + third-jump penalty + two-GREEN/20 s limiter | Caused zero/near-zero GREEN, while manual success counter also overcounted. Entire policy was reverted. |
| Treating delayed chicken motion as user reaction | Wrong. User clicks immediately; animation/CV confirmation is later. Keep timing split. |
| Learning every manual/no-GREEN success repeatedly | Wrong. Duplicate/false SAFE labels caused huge overcount. Only one low-weight SAFE sample per real target ownership switch. |
| Global fixed minimum processing FPS that disables the model | Wrong. At stable low FPS use frame-rate-aware lease margins; reserve hard blocking for true stalls. |
| Immediate target-switch = success with no survival | Too optimistic. Target switch can occur shortly before regression. Keep V5.5.0 provisional survival. |
| Old historical traffic permanently dominating current regime | Wrong. Current session/regime evidence must be authoritative. |

## Current V5.5.2 rule

Do NOT change normal-FPS V5.5.1 GREEN admission.

Only when processing is degraded (<2.8 FPS), require:
    frame margin = 1/FPS + 0.04 + 0.08 s

The +0.08 s is not another reaction budget. It is display/input headroom beyond
one sampled frame. In the supplied V5.5.1 failure:
    FPS ~2.3415
    lease ~0.4785 s
    old requirement ~0.4671 s
    surplus ~0.0114 s
The signal is therefore rejected.

At normal ~6.4 FPS, V5.5.2 adds no headroom and leaves V5.5.1 behavior unchanged.

If low FPS completely misses a jump animation, causal ownership may be recovered
ONLY from positive progress evidence:
- exact +1 target switch from GREEN snapshot,
- VIEW_SCROLL / explicit progress reframe,
- fresh chicken reappears around one lane left after scroll,
- bounded progress-handoff grace.

A crash/reset alone can never create a GREEN action.


## V5.5.3 addition

KEEP:
- local corridor gap history still resets on geometry reanchor
- bounded current-session gap prior survives reanchor
- prior alone can never authorize GREEN
- current lane must have mode-specific bootstrap support + P25 + headroom
- geometry-based RECHECK release is allowed only with fresh/stable landed geometry

DO NOT:
- preserve old corridor history as if it directly belonged to the new lane
- globally lower mature mode support from 8/9/10/12
- remove the V5.5.2 degraded-FPS headroom
