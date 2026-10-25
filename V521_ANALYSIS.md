# V5.2.1 analysis

From the 2026-10-10 14:57 session:

- 14 displayed GREEN episodes over ~68 minutes.
- 12/14 GREEN starts had zero active tracks.
- All 14 GREEN starts had dynamic_gap_ready=0 and gap_open_ready=0.
- V5 confidence at GREEN was still ~0.93-0.985.
- green_failures_learned=0 and green_successes_learned=0 for the whole run.
- green_late_unattributed increased to 4. Those actions were detected 1.25-1.82 s after GREEN ended while post_green_action_grace was only 0.75 s.
- The two crash records were not temporally adjacent to a displayed GREEN, proving crash/outcome attribution was missing the failures the user observed.

V5.2.1 therefore requires observable live-gap provenance and extends action attribution using stabilized chicken identity. A fresh safe-window model is used because V5.2 trained without this feedback.
