# V5.2.9 analysis — V5.2.8 run 2026-10-12 14:10:06

Run duration: ~163.7 min.

## Observed failures
- 34 GREEN signal IDs were created, but only 22 appeared as logged CLEAR episodes.
- Only 30 CLEAR frames were logged in the entire run.
- 18/22 visible GREEN episodes lasted <0.30 s; 15/22 were only one logged frame; only one lasted >=0.50 s.
- 9 GREEN-attributed actions were detected.
- green_outcome_successes stayed 0 for the full run.
- Only one GREEN failure was recorded/learned; 7 generic crashes were recorded.
- green_late_unattributed reached 9.

## Root causes
1. Outcome geometry used next_lane_distance clipped to 320 px while observed one-lane movement in this layout is commonly ~400-480 px. A successful jump could exceed the success envelope but remain below the chained-jump envelope, eventually becoming UNKNOWN.
2. The independent manual landing validator could bridge a scrolling success into GREEN outcome learning, but that bridge was inside passive_manual_success_enabled=false, so it never ran.
3. The manual jump validator rebased jump coordinates during viewport movement but retained the old viewport generation ID, causing same_view=false after normal game scrolling.
4. Sustained pre-commit did not guarantee a usable displayed GREEN. ML/provenance could change immediately after commit and collapse a mature GREEN into a ~0.15-0.30 s flash even while hard physical safety remained clear.
5. Slow-after hard protection works for the recent ~2.4 s post-slow window, but useful slow-before geometry almost never activated: slow_window_mode=slow-before occurred only once in 30,881 state rows. Vehicle-type expected speed was already learned but was not allowed to qualify an early likely-slow anchor unless the current track had already classified as S.

## V5.2.9 changes
- Preserve real target lane distance for outcome geometry (broad 700 px pathological cap only).
- Outcome snapshot prefers target_lane_distance over the old proxy.
- Validated GREEN success bridge now runs independently of optional passive/manual learning.
- Passive jump coordinates and viewport generation remain synchronized after viewport rebase.
- Post-GREEN action attribution grace: 2.1 -> 2.8 s; timing-only observation: 5.0 -> 6.0 s.
- Once GREEN is committed, keep it visible for at least 0.65 s only while all hard safety checks remain clear. Any hard hazard cancels immediately.
- Allow mature vehicle-type speed memory to identify a likely slow approaching anchor earlier; follower, direction and ETA checks remain authoritative.

## Safety preserved
No relaxation to visible-threat, uncertain-vehicle, live-gap, motion/MOG, target geometry, crash-memory, processing-health, recent slow-after guard, or physical ETA hard vetoes.
