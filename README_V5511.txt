V5.5.11 — crossing occupancy, consistent gap forecast, resolution-aware blobs

Start with start_v5511.bat.
Copy your existing data folder into this extracted build before starting.
Keep your previous build as the rollback copy. Models are not reset or bundled.

This build fixes three specific prediction/detection issues:
1. A clear upstream corridor no longer substitutes for a clear crossing strip.
   Independent raw occupancy now checks the buffered collision/landing strip,
   including a departing vehicle tail. It does not require a mature velocity ID.
2. EASY/NORMAL changes cannot lengthen a gap that is already open, or reduce
   its required budget mid-gap. Easing can apply to the next real gap.
3. Maximum foreground blob area now scales with capture resolution. A vehicle
   accepted at reference width must not be discarded just because it is larger
   in a 2x capture. Existing scene-change size filters remain in place.

Global ETA, probability, lease and cooldown settings are unchanged.
Slow-vehicle learning, model persistence, landing finality and target recovery
are preserved. Existing learned data is not erased or automatically relabelled.

New diagnostic CSV fields:
 crossing_motion_available / clear / ratio / reason
 dynamic_gap_unlatched_lower_bound
 detector_max_blob_area

Read V5511_INVESTIGATION.md for evidence, limits and verification. The patch
has not been validated in live gameplay; no improved success rate is claimed.
