Chicken Road 2 AI Live V5.3.9 - VERIFIED PHYSICAL OVERRIDE

Run: start_v539.bat

ROOT CAUSE
V5.3.8 still detected physically verified busy->clear gaps, but after prolonged
play the long-term + session classifier collapsed toward UNSAFE and suppressed
those opportunities. In the latest ~96.6 min run, GREEN decisions fell to zero
after ~60 min even though strong verified gaps remained.

FIX
A strong LIVE verified gap can now override only the ML probability when all
hard safety gates have already passed.

Override requires:
- physical heuristic >= 0.91
- dynamic confidence >= 0.75
- motion-gap support >= 12
- motion-gap P25 >= 1.80 s
- usable action lease >= 0.32 s and FPS-aware engine requirement
- raw risk <= 18
- motion ratio <= 0.04
- MOG <= 0.055

NOT RELAXED
- visible / uncertain vehicle veto
- target/chicken geometry
- processing / tracking / viewport veto
- slow-after / follower protections
- MOG/motion hard veto
- physical ETA and action-lease requirements
- crash-memory hard veto
- V5.3.8 causal outcome + fullscreen 3-lane reframe logic
- observed-clear/forecast remains strict at 1.58 s

LOG
SafeWindow telemetry is now safe_window_v539_*.csv.
`physical_override=1` on a verified gap can now represent this strong live
physical override even when the learned probability itself is low.

MODELS
Keep/copy:
  data/models/online_state_v532.joblib
  data/models/safe_window_v532.joblib
Do not delete them.
