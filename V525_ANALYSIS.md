# V5.2.5 Adaptive Optimization

The 2026-10-11 V5.2.4 run lasted about 176.9 minutes and produced only 8 visible GREEN episodes. The dominant issues were not a single over-strict rule:

- At 30-70 minutes, target geometry was lost and `tracking_roi_area_pct` became 100%. Motion processing rose from ~5 ms to ~170-188 ms median and overall processing fell to ~2.1-2.3 FPS, correctly blocking GREEN.
- After recovery, processing stayed ~6.4-6.6 FPS, but V5.2.4's final threshold clamp prevented the configured hard-game threshold from going below 0.90.
- Late-game hard-safe frames often had probabilities just below 0.90; the sustained commit also reset on every pre-commit probability dip.
- A long TARGET phase showed target distance ratio near 0.16, indicating the chicken had effectively reached the old target without target advance.
- Two crashes were logged; one was causally attributed to a displayed GREEN and remains in direct failure memory.

V5.2.5 preserves the V5.2.4 architecture and hard safety vetoes while fixing those bottlenecks.
