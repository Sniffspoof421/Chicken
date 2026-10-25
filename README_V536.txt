Chicken Road 2 AI Live V5.3.6 - GREEN RELIABILITY + PROGRESS STABILITY

Run: start_v536.bat

Main fixes from the 2026-10-13 05:20:34 telemetry:
1. Do not re-phase/reset the traffic corridor when the locked target is already
   one lane ahead of the chicken. This preserves live motion/gap evidence.
2. Observed-clear/forecast GREEN now needs an actionable ETA floor (1.58 s).
   Verified dynamic gaps use a lower 1.30 s floor because they contain direct
   busy->clear timing evidence.
3. Post-GREEN crash attribution grace is reduced from 2.8 s to 0.65 s.
   Later movement is timing-only and cannot become GREEN failure training.
4. Old GREEN-only failure memory learned under the contaminated attribution
   policy is cleared once on model load. Traffic, vehicle, crash and validated
   success memory are preserved.
5. V5.3.5 fullscreen third-lane reframe handling remains enabled.

Keep the game full-screen. Do not manually recenter the viewport during play.
The model filenames remain online_state_v532.joblib and safe_window_v532.joblib
for compatibility; V5.3.6 performs a one-time failure-policy cleanup at load.
