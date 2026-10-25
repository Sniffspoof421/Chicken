# V5.2.6 Opportunity Tuning

The V5.2.5 run showed scarcity rather than processing failure. Processing was healthy for 99.99% of state rows. There were 101 raw-safe bursts but only 9 sustained commits. Median raw-safe burst duration was about 0.23 s; 42 bursts lasted at least 0.30 s. Earlier failed flicker GREENs were about 0.14-0.21 s.

V5.2.6 therefore keeps the sustained-GREEN architecture but tunes commit dwell to 0.28-0.34 s, typically about 0.30-0.31 s in observed difficulty. It also advances a consumed target sooner when fresh stable geometry shows the next lane. No hard safety veto was removed.

Manual screen movement still triggers viewport rebase and motion rewarm, so keep the viewport stable whenever the next lane and incoming traffic are visible.
