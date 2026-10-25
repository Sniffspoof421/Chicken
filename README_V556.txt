V5.5.6 — successful landing update fix

START
Extract into a NEW folder and run start_v556.bat with your existing Python
installation. Copy your previous data folder into this new folder if you want
to retain your trained models. Do not delete or reset the previous models.

CONFIRMED FREEZE
After a completed manual/observed jump, main.py called the outcome bridge using
learning_chicken before that local variable had been assigned. Qt kept calling
the slot, which kept failing before clearing passive_jump and before updating
the widget. The predictor continued earlier in the tick, but the displayed
coordinates and target could stay frozen until another move changed the branch.

FIX
The already validated fresh_chicken is passed directly to the success bridge.
The completed jump can then clear and the same tick reaches target/state/UI
updates. The landing branch already requires fresh detection, stable viewport,
correct pre-action target geometry and completed rewarm; no safety condition is
removed by this variable fix.

The Qt timer now calls a guarded wrapper. A future tick error stops the displayed
GREEN, shows TRACK ERROR, records its traceback in the session folder under
runtime_errors_v556.log and retries the next scheduled tick. A repeated error
continues to show TRACK ERROR rather than a stale GREEN. Error logging is rate
limited. Successful ticks resume the normal UI. State CSV adds runtime_tick_errors,
runtime_tick_error_phase and runtime_tick_error_type.

PRESERVED
config.json is byte-identical to V555. No GREEN, ETA, confidence, cooldown,
lease, difficulty or detector thresholds were changed. Traffic learning,
manual-success weights, final landing lock, deadline expiry and reframe logic
remain in place. Safe-window logs use v556. The existing outcome_audit_v555.jsonl
filename is retained for compatibility. No learned model data is bundled.

TESTED
The full App.tick path reproduces UnboundLocalError in original V555 and passes
in V556. First landing: 190 -> 630, next target 1070. Second landing: 630 -> 1070,
next target 1510. Third-lane reframe: 1070 -> 190, next target 630. Tested with
small Y variation. An injected slot error revokes GREEN, writes a traceback and
recovers on the next successful tick. Existing V551–V555 regression tests pass.
These tests use a simulated camera/detector and real application update logic;
they do not establish live-game collision safety or detection accuracy.

See V556_INVESTIGATION.md for the evidence from your supplied logs.
