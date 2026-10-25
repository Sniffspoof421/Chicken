Chicken Road 2 AI Live - V5.2.6 Opportunity Tuning

This is a narrow optimization of V5.2.5. Core tracking, safety vetoes, failure learning, slow/follower logic and live-gap provenance are unchanged.

Run findings from 2026-10-11:
- 130.65 min session; processing healthy 99.99%.
- 101 raw SAFE bursts but only 9 committed V5 episodes.
- Raw SAFE burst median ~0.23s; 42 lasted >=0.30s.
- Previous failed flicker GREENs were ~0.14-0.21s.
- Target geometry was valid 98.2%, but target was <0.65 lane ahead for ~21.9% of states.
- 66 viewport-movement episodes caused rewarm/temporary GREEN suppression.

V5.2.6 changes:
1. Sustained GREEN commit tuned from ~0.36-0.40s to ~0.28-0.32s (bounded max 0.34s). Hard hazards still cancel immediately.
2. Consumed-target recovery starts sooner: target near-zone widened to 0.62 lane and hold reduced to 0.32s.
3. Pan/recovery logic itself is otherwise unchanged. Avoid unnecessary manual viewport movement because each pan still requires a brief motion rewarm.

Before first launch copy:
  data\models\online_state_v525.joblib
  data\models\safe_window_v525.joblib
from the trained V5.2.5 folder into this data\models folder.

Run start_v526.bat.
