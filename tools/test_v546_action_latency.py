import json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.outcome import GreenJumpOutcomeTracker
from app.adaptive import AdaptiveSessionModel
from app.risk import RiskEngine

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Real GO movement can appear >1 s after a short GREEN. It must still be
# causally attributed when a robust >=24%-lane displacement appears within the
# extended post-GREEN grace.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base={
    'indicator_state':'CLEAR','green_confirmed':True,'lane':1,
    'eta_source':'dynamic-gap','effective_eta':2.4,
    'raw_risk':2.0,'display_risk':2.0,
    'target_lane_distance':440.0,'target_lane_x':630.0,
    'target_lane_switches':1,'target_lane_lock_reason':'HOLD_SAME',
    'viewport_rebase_count':0,'chicken_fresh':True,
    'v5_gap_provenance':'verified-gap',
}
o.update(base,{'cx':190.0,'detected':True},10.0)
off=dict(base); off['indicator_state']='WAIT'
o.update(off,{'cx':190.0,'detected':True},10.30)

# 70 px is realistic detector wobble: still NOT an action with 24% lane rule.
ev=o.update(off,{'cx':260.0,'detected':True},11.55)
assert not any(x.get('kind')=='action_started' for x in ev),ev
assert o.acted_signals==0

# 120 px (>24% of 440) at 2.10 s after GREEN start / 1.80 s after end is
# a causal action, not "late/unattributed".
ev=o.update(off,{'cx':310.0,'detected':True},12.10)
started=[x for x in ev if x.get('kind')=='action_started']
assert started,ev
assert o.acted_signals==1,o.status()
assert started[0]['attribution']=='post_green_grace',started
assert o.active_attempt.get('timing_source')=='dynamic-gap',o.active_attempt

# 2) Movement after the 2.30 s post-end causal window is diagnostic only.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.update(base,{'cx':190.0,'detected':True},20.0)
o.update(off,{'cx':190.0,'detected':True},20.20)
ev=o.update(off,{'cx':320.0,'detected':True},22.70)
assert not any(x.get('kind')=='action_started' for x in ev),ev
assert any(x.get('kind')=='late_unattributed_action' for x in ev),ev
assert o.acted_signals==0

# 3) Fast traffic cannot remain EASY just because headways are generous.
m=AdaptiveSessionModel(cfg['risk'])
t=m.last_mode_update
motion={
    'support':30,'recent_support':15,'p25':2.4,'recent_p25':2.4,
    'gap_cv':.45,'busy_fraction':.25,
}
a=m.update_difficulty_mode(t+.1,motion,.82,.05,{})
assert a['mode_floor']=='HARD',a
m.update_difficulty_mode(t+1.0,motion,.82,.05,{})
b=m.update_difficulty_mode(t+2.0,motion,.82,.05,{})
assert b['mode']=='HARD',b

# Sparse but fast traffic is at least NORMAL.
m=AdaptiveSessionModel(cfg['risk'])
t=m.last_mode_update
motion2={
    'support':30,'recent_support':15,'p25':2.6,'recent_p25':2.6,
    'gap_cv':.35,'busy_fraction':.10,
}
a=m.update_difficulty_mode(t+.1,motion2,.76,.02,{})
assert a['mode_floor']=='NORMAL',a

# 4) Reaction budget ceilings are mode-aware and no longer globally capped .72.
r=RiskEngine(cfg['risk'])
assert r.mode_reaction_max['EASY'] >= .85
assert r.mode_reaction_max['NORMAL'] >= .95
assert r.mode_reaction_max['HARD'] >= 1.10
assert r.mode_reaction_max['EXTREME'] >= 1.20

print('PASS V5.4.6 causal late action attribution + anti-wobble + fast-traffic mode floor + mode reaction budget')
