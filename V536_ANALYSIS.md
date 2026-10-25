# V5.3.6 analysis — GREEN reliability and progressed-lane deadlock

Run analysed: `state_20261013_052034.csv`, `safe_window_v534_20261013_052034.csv`, `green_outcomes_20261013_052034.csv`, `green_failures_20261013_052034.csv`, `crashes_20261013_052034.csv`, `events_20261013_052034.csv`, and session telemetry.

## What the run actually recorded

- Runtime: ~68.1 minutes.
- Visible GREEN signal IDs: 6.
- Acted GREENs: 4.
- Resolved GREEN outcomes: 4.
- Recorded successes: 0.
- Recorded failures: 4.
- Therefore the logger's resolved/acted failure rate was 100% (4/4), not merely ~98%.

The four recorded failures were all classified as `late_causal_failure`.

| Signal | GREEN visible | Action delay from GREEN start | Action occurred after GREEN ended | ETA at GREEN |
|---|---:|---:|---:|---:|
| 2 | 0.768 s | 1.718 s | 0.950 s late | 1.159 s |
| 3 | 0.931 s | 2.976 s | 2.045 s late | 1.164 s |
| 5 | 0.787 s | 2.889 s | 2.102 s late | 1.427 s |
| 6 | 1.018 s | 1.706 s | 0.688 s late | 1.156 s |

V5.3.4/V5.3.5 allowed an action up to 2.8 seconds after GREEN ended to remain attached to that GREEN, and the learning layer could apply causal source penalties even later. That is too broad for a live traffic game: by then the traffic state that justified the GREEN is no longer the same state.

### Important correction to the first crash-log interpretation

The crash rows contain old `max_x` values near the third-lane position. Looking only at those maxima can make a later reset appear to be a normal 3-lane viewport reframe. Time-aligning `state.csv` to each GREEN shows those maxima were sometimes reached minutes before the GREEN action. At the actual failed-action windows, the chicken did not complete the required forward movement before reset. These should therefore not all be reclassified as successful third-lane progress events.

The useful conclusion is different: **an action that starts after the permission has expired must not be used as a clean supervised label for the earlier GREEN state**. A real crash may still be learned by the generic crash learner, but the expired GREEN itself must not be blamed.

## Root cause 1 — GREEN permission was physically too marginal

The six displayed GREENs began at effective ETA values of approximately:

`1.158, 1.160, 1.157, 1.393, 1.422, 1.158 s`

All were `observed-clear` rather than directly verified live-gap opportunities.

The project already has a conservative physical clear-window floor near 1.58 s. The V5 admission layer was overriding that down to ~1.08 s. With jump crossing ~0.55 s, safety buffer ~0.30 s, and learned/reaction allowance that can approach ~0.72 s, an unverified 1.15–1.43 s permission is not reliably actionable.

### V5.3.6 correction

- `observed-clear` minimum ETA: **1.58 s**.
- `tracked-forecast` minimum ETA: **1.58 s**.
- directly `verified-gap` minimum ETA: **1.30 s**.
- absolute internal floor remains 1.08 s, but it no longer permits an unverified observed-clear GREEN by itself.

This is intentionally evidence-dependent rather than a global threshold increase: a directly measured busy→clear gap may still be accepted earlier than an unverified empty-looking lane.

## Root cause 2 — expired GREENs were poisoning GREEN learning

Old policy:

- post-GREEN action grace: 2.8 s;
- late causal source-failure window: up to 3.6 s.

In this run every acted GREEN was detected only after the visible GREEN had ended, by 0.688–2.102 s. All four were nevertheless written as GREEN failures and fed back to the GREEN failure/source memory.

### V5.3.6 correction

- post-GREEN attributable action grace reduced to **0.65 s**;
- strong attribution reduced to **0.45 s**;
- an action beginning later becomes `late_unattributed_action`;
- if that late action crashes, the generic lane/crash learner may learn the crash, but **the expired GREEN source is not penalized**.

Under the new 0.65 s lease, all four actions from this run would be excluded from supervised GREEN attribution. That does **not** mean the crashes are ignored; it means the model stops pretending traffic 0.7–2.1 seconds after an expired GREEN describes the original GREEN state.

## Root cause 3 — the model erased its own traffic history on the progressed lane

The strongest progressed-lane failure is in `state.csv`.

There is one continuous period of roughly **27.7 minutes** with the chicken around x≈1072 and the next target around x≈1512. During that period:

- median target distance ratio ≈ **1.001 lane** — the target was already correct;
- target geometry was effectively the expected next lane;
- `V5 LIVE GAP UNVERIFIED` blocked ~4,670 logged states;
- motion-gap support median was only **1**, maximum only **6**;
- the dynamic-gap learner requires about **10** samples;
- therefore `dynamic_gap_ready` never became true.

Why did 27 minutes of traffic produce at most six retained gap samples?

The lane-phase synchronizer repeatedly treated small road-grid phase variation as a geometry fault. Across the full run:

- target-lane relocks: ~1,041;
- lane-phase realignments: ~1,005;
- `CHICKEN_PHASE_SYNC` telemetry rows: 566.

For all 566 `CHICKEN_PHASE_SYNC` rows, the target was already **0.978–1.059 lane ahead**. In other words, the authoritative chicken→target geometry was already correct.

Every unnecessary geometry reanchor called `risk.notify_geometry_reanchor()`, which clears the short-lived motion corridor, live motion samples, live gap history, and slow-motion gap history. The learner repeatedly did this:

`collect traffic → tiny road-grid correction → erase traffic evidence → start over`

That is the direct reason the progressed lane could remain stuck on `LIVE GAP UNVERIFIED` for many minutes.

### V5.3.6 correction

Before applying any lane-phase realignment, the synchronizer now checks the actual chicken→locked-target relationship. If the target is already inside the authoritative next-lane band (0.72–1.28 lane ahead):

- no phase realignment is performed;
- no traffic/motion history is erased;
- telemetry reports `TARGET_ALREADY_ALIGNED`;
- `lane_phase_realigns_suppressed` counts the prevented resets.

A true stale/misaligned target can still reanchor normally. The full-screen 3-lane reframe logic from V5.3.5 remains separate and intact.

## Root cause 4 — old GREEN-failure memory is contaminated

Earlier builds accumulated direct GREEN-failure prototypes under:

- the over-broad 2.8 s post-GREEN attribution window;
- the older reframe/reset bugs.

Keeping those direct failure prototypes would allow the repaired build to remain biased by outcomes that V5.3.6 would no longer label as GREEN failures.

### V5.3.6 migration policy

On first load of a pre-V5.3.6 model:

Preserved:
- long-term retrospective traffic classifier;
- vehicle/type/pattern learning;
- generic crash memory;
- successful GREEN memory and timing data.

Reset once:
- direct GREEN-failure prototypes/counters;
- GREEN source-failure ETA floors;
- direct SafeWindow failure-feedback prototypes created by the previous attribution policy.

The saved model is tagged with policy version 536 so this reset is not repeated on subsequent launches.

## What V5.3.6 should change in behavior

The exact six GREENs from this run would **not** be shown again because all six were unverified observed-clear opportunities below the new 1.58 s actionability floor.

The purpose of the phase-reset fix is then to let live busy→clear evidence accumulate normally on lane 3 / the progressed screen. Once that evidence reaches verified-gap support, the model may admit stronger windows using the 1.30 s verified-gap floor.

This means V5.3.6 should prefer **fewer but materially stronger GREENs**, while also avoiding the previous “stuck forever because support keeps resetting” failure mode.

This is not a promise of a particular GREEN count. The next run should be judged by:

1. `lane_phase_realigns_suppressed` increasing when minor road-phase jitter occurs;
2. `lane_phase_realigns` no longer climbing rapidly while target ratio is already ~1.0;
3. `motion_gap_support` being able to grow beyond 10 on a progressed lane;
4. `dynamic_gap_ready` eventually becoming 1 when traffic supplies enough busy→clear samples;
5. no GREEN from `observed-clear` below 1.58 s;
6. `green_late_unattributed` increasing rather than `green_outcome_failures` when an action begins after the 0.65 s lease;
7. V5.3.5 `fullscreen_reframe_count` continuing to increment only on genuine game reframes.

## Regression status

Passed on the V5.3.6 source tree:

- V5.3.6 expired-GREEN attribution + actionable ETA floors;
- V5.3.6 policy migration cleanup;
- V5.3.5 fullscreen reframe + GREEN outcome rebase;
- V5.3.4 current-session CZN speed authority + motion bootstrap;
- V5.3.3 chicken-authoritative geometry;
- V5.3.2 two-timescale session adaptation;
- V5.3.1 progress-scroll/Hardcore handoff;
- V5.3.0 self-advancing target;
- V5.2.9 outcome/slow/stable-GREEN regression.

An old V5.2.6 opportunity-tuning assertion that expected a ~1.4 s **unverified forecast** to be accepted is intentionally no longer valid. Restoring that assertion would recreate the marginal GREEN behavior observed in this failed run.
