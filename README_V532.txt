Chicken Road 2 AI Live — V5.3.2
Recent Adaptive / Long-Term Prior

Run: start_v532.bat

MODEL MIGRATION
Copy the trained V5.3.1 files into data\models before first launch:
  online_state_v531.joblib
  safe_window_v531.joblib
Do not copy .tmp files. V5.3.2 migrates them to:
  online_state_v532.joblib
  safe_window_v532.joblib

WHAT CHANGED
1. Two-timescale SafeWindow learning. Persisted history remains a long-term prior, but a fresh current-session SGD model is reset each launch and uses a constant learning rate so late-game evidence remains influential.
2. Long-term ML can no longer dominate current physical evidence. Before the session model matures, the blend is 60% physical heuristic / 40% long-term prior. With session support, the session model becomes the largest component (up to 60%), long-term history falls to 15%, and physics remains 25%.
3. Strong observed-clear override now requires either >=2 current CZN confirmations OR a strong measured lower-tail gap (P25 >=1.55s with >=12 samples). This blocks the V5.3.1 failed context with 0 current CZN events / ~1.40s P25 while allowing later strong ~1.85s P25 states.
4. Observed-clear physical ETA margin reduced from 0.05s to 0.01s for Hardcore, but only after the stronger evidence check above.
5. Added telemetry: v5_heuristic_probability, v5_longterm_probability, v5_session_probability, v5_session_train_n/safe/unsafe.

UNCHANGED HARD VETOES
Visible/uncertain vehicle, target geometry, active viewport motion, processing failure, MOG/motion, slow-after/follower, physical ETA, learned GREEN-failure memory, one-jump rearm.

IMPORTANT
Leave the game viewport alone during normal play. Automatic game scrolling is handled by V5.3.1/V5.3.2 progress-scroll logic.
