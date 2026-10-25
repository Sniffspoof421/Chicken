import json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.learning import OnlineLearner

cfg=json.loads((ROOT/'config.json').read_text())

# A target-switch landing is PROVISIONAL, not immediate success.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base={
 'indicator_state':'CLEAR','green_confirmed':True,'lane':1,
 'eta_source':'v5-safe-window','v5_gap_provenance':'verified-gap',
 'effective_eta':2.0,'raw_risk':2.0,'display_risk':2.0,
 'target_lane_distance':420.0,'target_lane_x':610.0,
 'target_lane_switches':1,'target_lane_lock_reason':'HOLD_SAME',
 'viewport_rebase_count':0,'chicken_fresh':True,
}
o.update(base,{'cx':190.0,'detected':True},10.0)
o.update({**base,'indicator_state':'WAIT'}, {'cx':320.0,'detected':True},10.6)
land={**base,'indicator_state':'WAIT','target_lane_switches':2,'target_lane_x':1030.0,'tracking_rewarm':True}
ev=o.update(land,{'cx':615.0,'detected':True},10.9)
assert any(e.get('kind')=='provisional_landing' for e in ev),ev
assert o.provisional is not None and o.active_attempt is None
assert o.successes==0

# Stable landing past the short survival grace becomes success.
ev=o.update(land,{'cx':617.0,'detected':True},11.25)
s=[e for e in ev if e.get('outcome')=='success']
assert s,s
assert o.successes==1
assert o.target_arrival_successes==1

# A landing that immediately regresses before the survival grace remains failure.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.update(base,{'cx':190.0,'detected':True},20.0)
o.update({**base,'indicator_state':'WAIT'}, {'cx':320.0,'detected':True},20.6)
ev=o.update({**land,'target_lane_switches':2},{'cx':615.0,'detected':True},20.9)
assert o.provisional is not None
ev=o.update({**land,'target_lane_switches':2},{'cx':190.0,'detected':True},21.15)
f=[e for e in ev if e.get('outcome')=='failure']
assert f and f[0].get('crash_reason')=='post_landing_regression',ev

# Non-target-switch stable landing can also succeed promptly: existing 0.30 s
# stable hold + 0.30 s provisional survival, rather than 1.5 s total.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.update(base,{'cx':190.0,'detected':True},30.0)
o.update({**base,'indicator_state':'WAIT'},{'cx':320.0,'detected':True},30.6)
# inside one-jump envelope and stable
for t,x in [(30.9,610.0),(31.22,612.0),(31.55,613.0)]:
    o.update({**base,'indicator_state':'WAIT'},{'cx':x,'detected':True},t)
assert o.provisional is not None
# another stable observation > .30 sec later
ev=o.update({**base,'indicator_state':'WAIT'},{'cx':614.0,'detected':True},31.88)
assert any(e.get('outcome')=='success' for e in ev),ev

# Source-specific learning uses physical timing source, not UI wrapper name.
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
    failure={
      'outcome':'failure','outcome_ts':100.0,'eta_source':'v5-safe-window',
      'timing_source':'dynamic-gap','eta':1.43,'lane':1,
      'attribution':'green_active','attribution_confidence':1.0,
      'one_jump_valid':True,'features':None,'safety_context':None,
      'speed_pattern':'-','type_pattern':'-','action_start_ts':100.1,
      'start_ts':100.0,'end_ts':100.5,
    }
    l.record_green_outcome(dict(failure))
    assert l.green_source_failures['dynamic-gap']==1,l.green_source_failures
    assert l.green_source_failures['v5-safe-window']==0,l.green_source_failures
    base_floor=1.30
    assert abs(l.source_failure_eta_floor('dynamic-gap',base=base_floor)-base_floor)<1e-9
    failure['outcome_ts']=101.0
    failure['eta']=1.46
    l.record_green_outcome(dict(failure))
    assert l.green_source_failures['dynamic-gap']==2
    assert l.source_failure_eta_floor('dynamic-gap',base=base_floor)>base_floor

print('PASS V5.5.0 causal landing survival + rewarm visibility + physical-source failure learning')
