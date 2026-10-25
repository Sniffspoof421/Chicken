Chicken Road 2 AI Live — V5.3.1
Progress Scroll + Hardcore ETA + Sustained Clear

Run: start_v531.bat

NORMAL USE
- Do NOT manually nudge/recenter the game screen during normal play.
- The game's own automatic road scroll after progress is expected and is now handled as a progress scroll.
- Move the window only if the next lane/traffic corridor is genuinely outside the capture.

MODEL MIGRATION
Copy these two files from the V5.3.0 folder you actually trained into data\models before first run:
  online_state_v530.joblib
  safe_window_v530.joblib

V5.3.1 migrates them to:
  online_state_v531.joblib
  safe_window_v531.joblib

Do not copy .tmp files.

V5.3.1 CHANGES
1. Game auto-scroll is clustered as progress scroll: pixels moving still blocks GREEN, but the post-scroll settle/rewarm is shortened and proposal-sync cannot fight the rebase during the cluster.
2. When eta_source is v5-safe-window, the final indicator uses v5_required_eta directly. The legacy ~1.7-1.8 s clear-zone requirement cannot veto a V5 hardcore decision.
3. A sustained physically-clean observed-clear lane may override a stale conservative classifier after all hard safety vetoes pass. It requires clear duration, gap history, ETA margin, low motion/MOG/raw risk and a minimum probability sanity floor.
4. All V5.3.0 target self-advance, MOG, visible/uncertain vehicle, slow/follower, crash-memory, outcome learning and sustained GREEN protections remain.
