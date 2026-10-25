Chicken Road 2 AI Live V5.5.1
CONVOY / RECENT-THREAT TAIL GUARD

Run:
  start_v551.bat

IMPORTANT
V5.5.1 is a narrow patch on top of V5.5.0.

It does NOT change:
- V5.5.0 causal landing survival logic
- V5.5.0 physical-source failure feedback
- V5.4.9 degraded-FPS behavior
- V5.4.7 GREEN lease profiles
- V5.4.5 centered post-pass timing
- difficulty modes
- current-session traffic learning
- one-GREEN / one-jump ownership
- fullscreen reframe logic

ROOT CAUSE FROM THE V5.5.0 RUN

Resolved acted GREENs:
  6 successes
  1 failure

Failure signal #19:
- GREEN ETA: ~2.19 s
- dynamic confidence: ~0.97
- motion gap P25: ~2.18 s
- three active tracks remained
- motion clear elapsed: ~0.44 s
- BUT time since the last direct high-risk/visible threat: only ~0.27 s
- next high-risk vehicle returned ~0.26 s after GREEN

This was a micro-gap between adjacent vehicles / convoy traffic.

The dynamic gap predictor believed the lane had entered a normal ~2.2 s gap
because historical gap statistics were strong. The motion-clear clock had also
started before the direct visible threat had fully cleared. So the existing
post-pass settle was not enough to distinguish a true traffic gap from a brief
transparent interval between two cars.

V5.5.1 FIX

A verified gap cannot START GREEN until the most recent direct threat has been
clear for at least 0.55 s.

New hard reason while waiting:
  THREAT TAIL SETTLE

This is independent from the motion-clear/post-pass clock.

Why 0.55 s?
In the supplied V5.5.0 run, replaying all 21 GREEN starts shows:
- failed signal #19: recent direct-threat age ~0.27 s
- all other 20 GREEN starts: above the 0.55 s threshold or no recent direct threat

Therefore this guard would reject/delay ONLY the recorded failed GREEN while
leaving the other 20 observed GREEN starts untouched.

The same physical gap becomes eligible normally once threat age reaches 0.55 s,
provided every existing V5.5.0 safety gate still passes.

NEW SAFEWINDOW TELEMETRY
  recent_threat_age
  threat_tail_settle_required
  threat_tail_ready

SAFE WINDOW LOG
  safe_window_v551_*.csv

MODEL FILES
Keep your existing model files. Do not reset them.
