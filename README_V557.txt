V5.5.7 — missing-tracking update recovery

RUN
Extract to a NEW folder and run start_v557.bat with your existing Python setup.
Copy your prior data folder into the new folder to retain trained model files.
Keep the old build/data as a backup. No model reset is needed.

CONFIRMED CAUSE
The supplied runtime_errors_v556.log repeatedly shows UnboundLocalError for nxt
at the risk.evaluate call. nxt was assigned only if both chicken and lane grid
were available. Losing either skipped that assignment but still evaluated nxt.
Every subsequent missing-tracking frame raised again. The error handler could
retry but could not repair that code path, so TRACK ERROR persisted. Its logged
error count reached 361. My previous tests covered successful landings but
missed this normal tracking-loss branch.

FIX
Initialize the frame's next-lane proposal as empty before any conditional ROI
selection. With no chicken/grid, the risk engine receives no lane override and
uses its existing no-tracking behavior. Frames continue through outcome handling,
logging and UI publication; GREEN remains blocked by the existing tracking gates.
When detection returns, the current chicken/target is selected normally.

The update-phase markers now identify chicken_detection, target_geometry,
vehicle_tracking, risk_evaluation and safe_window_prediction instead of leaving
those failures incorrectly labeled capture. Unexpected errors remain visible
and write runtime_errors_v557.log in the session folder.

PRESERVED
config.json is byte-identical to V556. No GREEN, detector, ETA, probability,
support, lease or cooldown setting changed. The V556 landing callback fix,
V555 display expiry, landing lock and supplemental manual learning remain.
No trained model data is included. Safe-window log prefix is now v557.
The existing outcome_audit_v555.jsonl name is retained for compatibility.

VALIDATION
The complete V556 update reproduces the supplied nxt exception. The complete
V557 update passes startup without chicken/grid, a ready grid without chicken,
400 missing-chicken frames (68 simulated seconds), lane-grid loss, combined
loss, and reacquisition at moved coordinates. Every tested frame reaches state
publication without TRACK ERROR; missing tracking never authorizes GREEN.
First/second landings and third-lane reframe tests still pass. Existing V551–V556
regressions pass. Main.py has no unbound/possibly-unbound variable diagnostics
in a targeted Pyright check, and Python modules compile.

These tests use controlled capture/detector inputs. They verify the reported
runtime freeze, not live-game vehicle detection or collision prediction accuracy.
See V557_INVESTIGATION.md for details.
