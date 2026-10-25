# V5.2.7 Visible Outcome + Tiered Lease

This is a narrow correction to V5.2.6 based on the 2026-10-12 run.

## Findings
- 30 GREEN signals / 12 acted signals were counted, but GREEN-specific success/failure learning stayed at zero while generic crash learning recorded crashes.
- Outcome attribution was cancelled by viewport/camera movement, so an acted GREEN could lose ownership before landing/crash.
- Most GREENs were forecast/observed-clear signals with ETA around 1.08-1.14 s; only a small minority had measured dynamic/gap-open confirmation.
- Historical post-slow headways were often short (~0.94 s p25) but were not influencing forecast admission.

## Changes
1. Acted GREEN attribution is rebased across viewport movement instead of cancelled. Unacted GREEN permission is still cancelled on a view change.
2. Outcome tracking only registers a visible, confirmed CLEAR state.
3. Tiered admission without recreating the old global ETA wall: verified measured gaps keep the 1.08 s floor; tracked forecasts use 1.18 s; empty observed-clear lanes keep the physical floor but must prove >=0.70 s current clearance and >=1.10 s current gap P25.
4. Risky historical slow-after profiles add a bounded forecast penalty; for observed-clear lanes they veto only when the *current* gap profile is also short (<1.25 s). Recent slow-after hard guard is unchanged.
5. Outcome timeout is extended to 5.5 s so the displayed GREEN remains the owner until a realistic jump resolves.
6. New telemetry records gap provenance, required V5 ETA, historical slow-after risk, GREEN outcome counts and viewport rebases.
