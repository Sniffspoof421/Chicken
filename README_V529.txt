Chicken Road 2 AI Live — V5.2.9
Outcome Geometry + Slow-Before + Stable GREEN

Run: start_v529.bat

MODEL MIGRATION
Preferred: copy these two files from the V5.2.8 folder you actually trained into data\models before first run:
  online_state_v528.joblib
  safe_window_v528.joblib

V5.2.9 will migrate them to:
  online_state_v529.joblib
  safe_window_v529.joblib

Do not copy .tmp files.

Key changes:
- correct real lane-distance GREEN success geometry
- GREEN success learning works even with passive manual learning disabled
- successful scrolling jumps can still be credited after viewport rebase
- matured GREEN remains visibly stable through soft ML/provenance jitter while hard hazards still cancel immediately
- learned vehicle-type speed can help identify approaching slow vehicles earlier
- outcome action attribution extended modestly for this game's observed visual-action delay
