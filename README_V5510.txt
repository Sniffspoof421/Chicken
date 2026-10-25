V5.5.10 — landing evidence and incoming trajectory guard

Run start_v5510.bat. Copy your existing data directory into this extracted
folder before starting to retain your current learned model. Keep the old
folder as your rollback copy. No trained data is bundled or reset.

Changes:
- Target switch alone no longer finalizes a GREEN success. Fresh detections
  must settle at the pre-jump ground height for the existing landing hold.
- Final settled success remains irreversible. In-flight/death-animation target
  switches remain owned until resolved, so regressions can still be learned.
- Coordinate-only VIEW_SCROLL handoffs resolve UNKNOWN rather than SAFE.
- Viewport cancellation writes an explicit UNKNOWN instead of losing a cue.
- An incoming car with two consistent measured positions can veto GREEN before
  three-frame direction lock. One-point, lateral, stale and reverse tracks cannot.

No global admission/configuration thresholds or slow-vehicle learning changed.
Earlier stored labels are preserved; this patch prevents the demonstrated false
SAFE paths going forward. It does not retroactively repair existing weights.

See V5510_INVESTIGATION.md for evidence and verification. Live crash frequency
has not been measured on this patched build.
