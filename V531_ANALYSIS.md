# V5.3.1 analysis and fixes

The V5.3.0 run/video showed three independent late-game blockers:

1. The game's own road discard/auto-scroll was fragmented into repeated scene-pan/re-warm cycles. V5.3.1 clusters those pans as progress scrolls, still blocks while pixels move, but ignores only the raw detector's long post-pan hold tail and uses a shorter rewarm. Proposal-sync is suppressed during the short scroll context so it cannot fight the coordinate rebase.
2. V5 safe-window used ~1.08-1.14 s hardcore ETA, while the outer legacy indicator could still expose ~1.7-1.8 s clear-zone requirements. V5.3.1 explicitly hands `v5_required_eta` to the indicator whenever V5 is the active source.
3. Late physically clean `observed-clear` states were often vetoed solely because the learned classifier was ~0.5 while its floor stayed ~0.8+. V5.3.1 adds a sustained physical override only after all existing hard vetoes pass, with additional clearance, gap-history, ETA-margin, motion, MOG, raw-risk and probability-sanity checks.

No global ML threshold reduction was made. Visible/uncertain vehicle, target geometry, motion/MOG, slow-after/follower, processing, crash-memory and sustained-GREEN hard protections remain authoritative.
