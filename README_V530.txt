Chicken Road 2 AI Live — V5.3.0
Self-Advancing Target + Late Failure Learning

Run: start_v530.bat

NORMAL USE
- Keep the game/model viewport stationary during normal play.
- Do NOT nudge the screen to wake tracking.
- Move the viewport only when the next lane/traffic corridor is genuinely outside the visible area.

MODEL MIGRATION
Copy these two files from the V5.2.9 folder you actually trained into data\models before first run:
  online_state_v529.joblib
  safe_window_v529.joblib

V5.3.0 will migrate them to:
  online_state_v530.joblib
  safe_window_v530.joblib

Do not copy .tmp files.

Key changes:
- consumed-target recovery no longer depends on the same stale nearest-lane proposal
- independently selects a detected lane center roughly one spacing ahead
- stale/consumed proposals cannot pull the recovered target backward again
- ordinary target GREEN phase allows modest camera compression; verified slow-before can use a slightly closer valid target
- preserves V5.2.9 success geometry, stable GREEN, hardcore admission, slow/follower safety, MOG and failure memory
- causal GREEN failure-learning window extended to include the observed ~3.28 s acted failure instead of discarding it
