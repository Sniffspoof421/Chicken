V5.5.5 — display action-lease expiry and causal reset ownership

RUN start_v555.bat after extracting into a new folder. Use the same Python
installation as V554. Copy your previous data/model folder if retaining learned
state. Do not delete the existing model. config.json is unchanged byte for byte.

WHAT CHANGED
A verified-gap GREEN now has a wall-clock deadline derived from its EXISTING
remaining action lease. A precise UI timer expires it between analysis ticks;
paint and pre-admission guards also reject an already-expired display. This
removes stale green presentation rather than raising admission thresholds.
A desktop event-loop stall can still delay repaint; this is not a hard real-time
system. The initial lease/probability/support/ETA/cooldown settings are unchanged.

A pending or confirmed reset cannot synthesize a progress-scroll jump attempt.
A delayed confirmed crash whose original timestamp precedes an inferred action
resolves UNKNOWN and cannot train as a GREEN failure or success. Genuine actions
observed before a crash retain their existing failure path. Final landing locks
and valid progress-scroll handoffs are retained. The new audit JSONL retains
unknowns so exclusions remain visible rather than silently improving statistics.

LOGGING
state CSV adds decision_frame_timestamp, green_display_deadline,
green_display_expired, reset_candidate_pending, reset_confirmed_this_tick.
outcome_audit_v555.jsonl in the session log folder records all resolved GREEN
outcomes, including unknowns and chronology. Safe-window logs are tagged v555.

Read V555_INVESTIGATION.md for findings and limits from the supplied run.
