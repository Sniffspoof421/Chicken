Chicken Road 2 AI Live V5.4.2 — STABLE ACTION WINDOW

Run: start_v542.bat

Main fixes:
1. No GREEN unless a verified gap has >=0.55 s extra action lease.
2. Strong verified gaps can bypass stale ML with strict live-physics checks.
3. Chicken detector wobble cannot create false JUMPING: action start is lane-scaled.
4. Unacted GREEN cooldown is cycle-aware instead of blocking all new gaps for 6 s.
5. Active GREEN cancels early on a sharp motion/MOG/raw-risk rise.

Keep existing models:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib

Do not delete them.

Expected next-run behavior:
- fewer one-frame marginal GREENs
- more GREENs on high-lease/high-confidence verified gaps
- no multi-second JUMPING state from 50-70 px chicken-position wobble
- no six-second blackout when a genuinely new traffic gap opens

New SafeWindow log: safe_window_v542_*.csv
