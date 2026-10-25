# Investigation of the V5.5.10 run 20261022_182623

## Result and attribution

The state log spans 47.33 minutes and 8,516 sampled rows. The signal audit has
40 GREEN starts and 15 inferred actions. There are 11 classified outcome rows:
seven successes and four failures. Failure 7 is already training-ineligible
(`late_outside_causal_window`) and its ownership is synthetic scroll-based.
The other three, signals 21, 29 and 40, are training-eligible regressions.
The audit also contains 13 UNKNOWN outcomes. There are 19 reset rows in the
crash CSV, and zero runtime tick exceptions in the sampled state log.

Seven successes / (seven successes + three eligible failures) = 70% among
these labelled causal outcomes. This is not a video-verified accuracy estimate.
The other resets are unassigned; these files do not prove they were all manual,
and they must not all be charged as GREEN failures. UNKNOWN outcomes and
unacted cues are excluded from that denominator.

V5.5.10 correctly retained failure evidence instead of prematurely finalizing
these three jumps as successes. That bookkeeping fix did not solve every
physical detection/admission problem. The remaining changes below target
specific spatial, temporal and resolution inconsistencies.

## Findings

### 1. Crossing strip omitted from the clear motion corridor

`RiskEngine._incoming_motion_corridor` ends its upstream rectangle at
`chicken_y - crossing_half_height`. Consequently a car can leave this rectangle
while its body/tail still overlaps the buffered collision strip. Direct tracked
vehicle geometry may catch this, but it requires a usable direction/velocity
track. No GREEN start in this run had an available upstream trajectory.

Near signal 40, a session row contains a box centred around (659, 802), width
194 and height 66, while the chicken is around y=731. Its upper edge is about
769: below the old corridor's end (~673), but inside the buffered crossing.
Its reported vy is zero, so a positive-direction vehicle guard cannot resolve
this occupancy. This is evidence of the spatial blind spot, not proof of which
specific vehicle killed the chicken. Original pixel masks/video were not
included in the upload, and a foreground bounding box is not itself ground truth.

The fix measures the actual raw foreground mask in a separate landing/collision
strip. It uses the existing corridor width and motion-ratio tolerance, plus
existing chicken/crossing collision extents. The strip must be fully covered
by the ROI. This is a hard physical veto before V5 admission and is reapplied
before indicator admission; an active-GREEN hold or physical probability
shortcut cannot bypass it. A vehicle farther upstream remains governed by the
existing arrival logic. A passed vehicle or adjacent lane does not trigger
this strip check.

This leaves upstream gap learning and its existing support/threshold logic in
place. It adds the missing occupancy question, rather than globally increasing
ETA, leases or probability. Slow departing tails also benefit without changing
the slow-profile learning policy.

### 2. An open gap gained time when mode eased

Signal 40 uses cycle 877. On its first sampled clear frame, the lower-bound
estimate is 1.82582097 seconds and the required budget is 1.42742434 seconds.
Within the same cycle, mode changes NORMAL -> EASY, quantile changes 22 -> 25,
and the estimated bound rises to 2.07702923 seconds. The required budget also
falls to 1.38143360 seconds. At the sampled GREEN frame, effective clear age
is already 0.51872474 seconds. These changes manufacture additional headroom
without observing a new gap or an incoming vehicle trajectory.

The new per-episode latch permits the bound only to shrink and the required
budget only to grow until the next actual cycle. Temporary unavailable evidence
cannot reset it. New cycles and explicit geometry reanchors get a new forecast,
so learned easing remains useful for subsequent opportunities.

Recorded-state replay shows that the sampled GREEN frame of signal 40 lacks
its required remaining budget under the original episode bound. This checks
the forecast correction; it is not a replay of all captured frames or input.

### 3. Fixed pixel-area limit rejected scaled vehicles

The detector used a fixed max_blob_area=50,000 with no capture-resolution
normalization. A vehicle's area quadruples when capture dimensions double.
That can discard intact vehicle blobs before tracking even starts; lowering
track-age requirements cannot recover a contour that was discarded.

A real MotionEngine/MOG/diff/morphology regression test reproduces the bug:
a synthetic vehicle is accepted at 1280 width, rejected by the legacy fixed
limit at 2560, and accepted by the corrected area scaling. Max area scales
upward in squared pixels from reference width 1280. Existing minimum filters
and near-full-ROI scene-change rejection remain. The uploaded logs do not
contain rejected contours, so the exact number of missed live cars cannot be
computed from this run.

## Individual failures and timing limits

- 21: visible target-sized displacement followed by regression. A smaller
  fresh displacement is sampled about 0.406 seconds after GREEN, earlier than
  the large-motion confirmation at ~0.965 seconds. Calling that latter value
  the user's click latency would be incorrect. Upstream prediction unavailable.
- 29: target-sized displacement followed by regression. Sampled coordinates
  remain near the baseline for over a second after GREEN; the first large
  fresh movement comes later. Actual input time is not recorded, so these
  files cannot distinguish delayed input from game/render/detection latency.
- 40: target-sized displacement and regression, with the within-cycle mode
  easing issue reproduced above and a foreground box in the omitted strip.
- 7: synthetic scroll ownership, marked ineligible. Retained as an audit event,
  excluded from supervised GREEN failure learning and the labelled rate.

No failure has been silently relabelled as a success, and no unassigned manual
reset has been turned into an eligible GREEN failure. The exact collision cause
for 21 and 29 cannot be proven without frame/input evidence. The patch fixes
three demonstrated code paths; it cannot promise that every future crash is
eliminated, particularly when vehicles are not detected at all.

## Preservation and verification

config.json is byte-identical to V5.5.10. The chicken detector, target-lane
recovery, outcome/landing state machine, slow-profile learner and checkpoint
logic are also unchanged. Existing trained files are retained and not reset.

All 14 checks passed: existing slow profile/geometry, threat-tail, degraded-FPS
handoff, gap bootstrap, landing/upstream, reset/display, actual Qt expiry,
full App.tick first/second jump and third-lane reframe, long tracking-loss and
reacquisition, missed-GREEN rearm, persistence/learning, V5.5.10 landing evidence,
and the new crossing/forecast/resolution tests. The new suite also checks that
an active hold with probability .999 cannot bypass crossing occupancy, that
cropped coverage is handled correctly, that passed/upstream/adjacent vehicles
do not trigger the new strip veto, and that state CSV columns stay aligned.

No live patched run has been measured. New telemetry exposes crossing status,
unlatched versus applied forecast, and the effective detector area limit for
validation of this specific fix in the next run.
