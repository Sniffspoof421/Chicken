Chicken Road 2 AI Live V5.4.6
CAUSAL ACTION LATENCY + FAST-TRAFFIC MODE FLOOR

Run: start_v546.bat

ROOT CAUSES FOUND IN THE V5.4.5 RUN

1) GREEN OUTCOMES WERE NOT LEARNING
- V5.4.5 generated 38 GREEN signals.
- green_acted remained 0 for the entire run.
- green_outcome_successes = 0.
- green_outcome_failures = 0.
- Real one-lane movement often became visible 1.2-2.2 seconds after GREEN ended.
- post_green_action_grace was only 0.65 seconds.

Result:
The user could click GO on GREEN, jump/crash/succeed, but the model classified the
movement as late/unattributed instead of attaching it to that GREEN.

2) ANTI-WOBBLE FIX MADE ACTION CONFIRMATION LATER
V5.4.2 correctly rejected ~50-70 px detector wobble, but the larger movement
threshold means real jump confirmation naturally arrives later. The causal grace
was never updated to match that stronger confirmation threshold.

3) REACTION LEARNING SOURCE MISMATCH
GREEN snapshots use eta_source=v5-safe-window, while RiskEngine requests reaction
timing under dynamic-gap. Even a validated success could therefore fail to update
the timing budget used by verified-gap GREEN decisions.

4) FAST TRAFFIC COULD STILL REMAIN EASY
The difficulty score intentionally weighted gaps heavily. In this run multiple
GREEN states had live_speed_difficulty_score ~0.81-1.00 while the controller still
reported EASY/NORMAL. Fast-returning traffic is dangerous during click->jump
latency even when average headways look generous.

V5.4.6 FIXES

A) CAUSAL ACTION WINDOW
- post_green_action_grace: 0.65 -> 2.30 seconds.
- late observation window: 3.20 seconds.
- strong attribution window: 1.20 seconds.
- A real fresh forward movement inside this causal window can now own the GREEN.

B) STRONGER ANTI-WOBBLE CONFIRMATION
- action confirmation requires >=24% of one lane.
- A 50-70 px stationary detector wobble still cannot create JUMPING.
- The longer causal window compensates for this safer/later confirmation point.

C) SUCCESSFUL TIMING NOW TRAINS THE RIGHT SOURCE
- Verified-gap GREENs carry timing_source=dynamic-gap.
- Observed-clear GREENs carry timing_source=clear-zone.
- Validated successes now feed the reaction budget actually used by RiskEngine.
- Successful action delays up to 2.8 s may be retained as timing evidence.

D) MODE-AWARE REACTION BUDGET
The old global maximum was 0.72 s.
V5.4.6 allows modestly larger learned budgets without making every mode equally
conservative:
- EASY max: 0.85 s
- NORMAL max: 0.95 s
- HARD max: 1.10 s
- EXTREME max: 1.20 s

These are intentionally below raw CV movement delay because the movement
confirmation threshold itself adds detection latency.

E) FAST-TRAFFIC MODE FLOOR
Current live traffic can force a minimum difficulty mode:
- very fast + meaningful density/busy traffic -> HARD floor
- fast sparse traffic -> at least NORMAL
- dense traffic can also force NORMAL/HARD

Hysteresis remains active, so modes do not flicker frame-to-frame.

F) SAME-CYCLE REARM CORRECTION
With the longer causal window, the old unacted cooldown could already be expired
by the time a signal was classified unacted. The cooldown now starts when the
signal is actually classified unacted.
- same traffic cycle: suppressed
- genuinely new busy->clear cycle: allowed immediately

PRESERVED
- V5.4.5 centered GO-NOW/post-pass timing
- V5.4.4 difficulty/regime switching
- V5.4.3 adaptive verified lease
- one GREEN = one jump
- no crash-progress fabricated actions
- fullscreen third-lane reframe
- target-switch handoff
- current-session speed guard
- physical verified-gap ML override

MODELS
Keep:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do not delete them. V5.4.6 needs validated outcomes to begin learning the real
current click/jump timing correctly.

LOG
SafeWindow telemetry: safe_window_v546_*.csv
