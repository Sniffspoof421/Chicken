# Chicken
The strongest improvements were in tracking, recovery, and outcome bookkeeping. Reliable GREEN accuracy was never established. Several fixes passed code tests, but later sessions still showed crashes, scarce cues, and unresolved outcomes. I should have distinguished “bug fixed in tests” from “improved in live play” more consistently.

This summary reflects the conversation and investigations already recorded; it is not a fresh re-analysis of every historical file.
Actions taken and results
Area	Actions taken	What worked / what remained unresolved
Traffic and gap learning	Replaced older heuristics with future-safe-window learning; added speed calibration, vehicle histories, gap statistics, and difficulty regimes.	Some sessions produced useful GREENs, but historical gaps did not reliably account for individual incoming vehicles or convoys.
Chicken and target tracking	Improved chicken identification, chicken-relative lane geometry, target advancement, and fullscreen reframing.	Addressed specific stuck-target cases. Later reports showed that detection loss and camera transitions still needed handling.
Runtime recovery	Fixed a tracking exception; added recovery for frame gaps, stale detections, and degraded FPS.	Targeted regression tests passed. This improved resilience, without proving better prediction accuracy.
GREEN timing	Adjusted cue timing after passing vehicles; separated real input time from delayed visual movement; added display deadlines.	Made timing and attribution more explicit. Many cues remained brief: one reviewed pair of sessions had a median painted duration of about 0.34 seconds.
Repeated GREENs	Added missed-cue rearming that requires a new traffic cycle.	Addressed repeated signals from the same opportunity. Overall live benefit was not established.
Upstream threats	Added trajectory-based arrival estimates, retained mature lost tracks, and considered multiple incoming vehicles.	Addressed weaknesses in looking only at the current crossing area. Missing or uncertain tracks remained a limitation.
Landing and crash ownership	Added provisional landing, settled-ground confirmation, final-success protection, and camera-transition exclusions.	Improved separation of completed jumps from later resets. Merely reaching target x proved insufficient because the chicken could still be airborne.
Learning labels	Excluded late/off-cue actions, separated manual and automatic inputs, fixed inconsistent training eligibility, and extended outcome handling.	Important corrections to training-data quality. Several attempts still ended UNKNOWN, so feedback remained incomplete.
Automatic Space	Added foreground checks, F9 enabling, F10 stopping, diagnostics, and one-send-per-cue handling.	V5.5.21 logs confirmed enabling and a send attempt. No movement was confirmed, so end-to-end operation was not established. Enter remained manual.


What the measured results actually showed
- V5.5.3: The supplied summary reported 40 GREENs, 21 acted on, and 19 resolved: 16 successes and three logged failures. Excluding one ineligible failure gave 16/18 = 88.9%. The suggested 17/18 ≈ 94.4% depended on correcting a suspected landing-label error; it was not a verified overall accuracy.
- Two later V5.5.17 sessions: 43 painted GREENs over approximately 81.9 minutes. Logged resolved outcomes were five successes and three failures: 62.5% among resolved outcomes only. Under stricter recorded-input attribution, there was one success, one failure, and two unknowns—too little evidence for a dependable accuracy estimate.
- Latest V5.5.21 automatic attempt: One send was logged, no movement was confirmed, and the result was UNKNOWN. It provides no success-rate estimate.
These runs used different attribution rules and had incomplete outcomes. They cannot support a clean claim that accuracy improved—or a precise percentage decline.
What did not work well
Repeated global tightening was the clearest unsuccessful pattern. Increasing ETA, lease, support, or cooldown requirements often reduced GREEN availability without demonstrating that the remaining signals were reliably better.

Other recurring problems were:
- Treating historical gap statistics as strong evidence that no vehicle would arrive.
- Changing prediction decisions while success/failure labels were still unreliable.
- Treating unresolved attempts as if they could simply be omitted from performance reporting.
- Inferring delivery from an internally generated input record.
- Releasing builds after regression tests without enough comparable live validation.
Insights for slow-vehicle learning
I can help evaluate slow-vehicle perception and learning in recorded footage or a non-wagering simulation. I can’t help optimize live betting signals or automatic casino play.

For that offline work, the most useful improvements are:
Improvement	Why it matters
Label complete vehicle passages	Record first appearance, crossing-zone entry, rear clearance, and occlusion. A vehicle’s centre passing is different from its full body clearing.
Separate vehicle size from speed	A long slow vehicle occupies an area differently from a short slow vehicle. Speed alone loses that distinction.
Keep track identity through brief occlusions	A reappearing slow vehicle should not automatically become a new vehicle with an empty history.
Measure uncertainty alongside speed	Sparse observations, camera movement, and noisy boxes should reduce confidence in the estimate.
Annotate following vehicles separately	An apparent “slow-vehicle failure” may actually involve a faster follower. That distinction requires footage, not just outcome counters.
Evaluate before and after passage separately	They involve different visibility and tracking conditions; combining them hides systematic errors.
Split evaluation by session	Adjacent frames from the same passage should not appear in both training and test sets. That would inflate performance.


The key unresolved question is whether the model fails to observe a vehicle, estimates its motion incorrectly, or assigns the wrong outcome afterward. Those are three different problems. More training on mixed or incorrect labels can reinforce the error.

The most useful next deliverable would be an offline, annotated replay benchmark containing slow vehicles, fast followers, camera shifts, and detection loss. Compare each version on vehicle tracking, arrival-time error, and outcome-label correctness using the same recordings. That would show which changes actually help before making further claims about improvement.
