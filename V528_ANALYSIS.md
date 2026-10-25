# V5.2.8 Hardcore Adaptive

The V5.2.7 hardcore run lasted ~22.5 minutes and produced zero GREEN. Required ETA was only ~1.08-1.20 s, not 1.6 s. The real blocker was confidence: 3,729 hard-safe inference rows existed, but only 12 crossed the absolute ~0.89-0.91 ML threshold and none survived sustained commit.

V5.2.8 keeps all hard vetoes and V5.2.7 visible-outcome attribution. It adds provenance-aware final confidence floors after hard safety passes, and difficulty now responds to live speed plus compressed gap p25. Weak/unverified forecast remains on the original ML threshold. Offline replay of the supplied V5.2.7 run yields roughly 20-30 stable candidate commitments instead of zero.
