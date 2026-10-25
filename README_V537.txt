Chicken Road 2 AI Live V5.3.7 - VERIFIED GAP FAST PATH

Run: start_v537.bat

ROOT CAUSE FIX
- V5.3.6 DID learn live traffic, but it waited twice after the same verified busy->clear gap.
- RiskEngine already validates the physical gap and action lease.
- V5.3.7 skips the duplicate SafeWindow clear dwell and duplicate commit dwell for dynamic-gap only.
- A new verified-gap GREEN still needs an FPS-aware extra action lease:
    max(0.28 s, 1/FPS + 0.04 s, RiskEngine lease floor)
- Once admitted, the same verified gap can remain GREEN for its bounded action lease.
- Real hazards cancel immediately.
- Observed-clear/forecast stays strict at 1.58 s.
- Fullscreen 3-lane reframe and V5.3.6 chicken/target stability fixes are preserved.

NEW SAFE-WINDOW TELEMETRY
- verified_gap_fastpath
- verified_gap_action_lease
- verified_gap_min_action_lease
- verified_gap_held
- verified_gap_hold_remaining

The SafeWindow CSV is now named safe_window_v537_*.csv.

MODEL FILES REMAIN COMPATIBLE
Copy your existing trained files into data/models if not already present:
  online_state_v532.joblib
  safe_window_v532.joblib
