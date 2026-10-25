# Investigation of persistent TRACK ERROR in V556

Sources: runtime_errors_v556.log and all seven supplied run data files dated
20261022_005928, including the outcome audit. Originals were not modified.

## What failed

Every supplied runtime traceback identifies the same statement in main.py:

    lane_override=(nxt[0] if nxt else None)

The exception is UnboundLocalError: nxt has no local value. The variable was
assigned only inside `if chicken is not None and self.lanes.ready`. The call to
risk.evaluate was outside that conditional, so ordinary chicken loss or a lost
lane grid reached the call with no nxt assignment for that frame.

The handler retries on future ticks. Because the missing-tracking condition
continues, the same exception repeats. Repeating an errored tick does not repair
its uninitialized local. The traceback count reaches 361 at timestamp
1792612111.760110. Successful state publication ends earlier at
1792612058.509770, consistent with the later repeated exceptions preventing
publication. The label phase=capture was too broad: the actual failure was
risk evaluation after capture had completed.

This is separate from the learning_chicken landing bug fixed in V556. The new
runtime log made this second branch defect explicit. Previous tests exercised
valid detections and landed positions, so they did not cover its trigger.

## Change

V557 initializes `nxt=[]` before the conditional target/ROI selection. That is a
per-frame empty proposal, never a retained old target. With lost tracking the
risk engine receives lane_override=None and returns its normal missing-chicken
or missing-lane result. Existing vision, target and outcome checks keep GREEN
blocked; frame processing can still update the widget and later reacquire.

The general runtime error wrapper remains. More precise phase markers identify
future errors. New runtime errors use runtime_errors_v557.log. Predictor logs
use safe_window_v557. Configuration and learned-model paths are unchanged.

## Application-level reproduction and recovery tests

The test calls the real App.tick function with controlled screen/detection
inputs and real state/target/learner integration. Pointing it to V556 reproduces
the exact supplied exception. V557 completes all of these scenarios:

| Scenario | Updates completed |
|---|---:|
| Startup with no chicken or lane grid | 12 |
| Lane grid available, chicken absent | 12 |
| First chicken reacquisition | 16 |
| Prolonged chicken loss | 400 |
| Chicken returns at moved X | 16 |
| Chicken available, lane grid absent | 12 |
| Chicken and grid both lost after landing | 16 |
| Grid returns before chicken | 12 |
| Current-position reacquisition | 16 |

Each update must reach state publication. The 400-frame loss spans 68 seconds
of simulated clock time, exceeding the existing hold/reacquisition timeouts.
No tested dropout produces a tick exception or a GREEN. Restored detection at
X630 selects target X1070; restored first-lane detection at X190 selects X630.
No manual screen movement or application restart is required by the test.

The prior full-tick landing test also passes first/second landings, small Y
variation, third-lane reframe, and injected-error revocation/recovery. V551–V555
regressions and the Qt deadline callback pass. config.json is byte-for-byte V556.
A targeted Pyright check of main.py reports zero unbound/possibly-unbound
variable diagnostics; this is not a claim that the legacy project has no other
type-checking warnings. Python modules compile.

## Limits of the conclusions

The state file spans about 18.148 minutes before its final successful write.
It contains four logged GREEN successes, and the crash file contains nine reset
detections. Those records do not establish physical jump success rates: causal
attribution and visual reset/reframe classification remain separate concerns.
This patch fixes the confirmed runtime error; it does not relabel crashes or
claim to eliminate physical collisions. A live Windows gameplay run was not
performed here, and controlled detector inputs do not validate image accuracy.

Run tools/test_v557_tracking_loss.py to repeat the new regression. An optional
path argument selects an older build for reproducing the original exception.
