from app.indicator import StableRiskIndicator
from app.outcome import GreenJumpOutcomeTracker

cfg={
 'green_threshold':36,'green_exit_threshold':48,'yellow_threshold':55,'red_threshold':70,
 'stable_low_seconds':0.0,'evidence_stable_seconds':0.0,'dynamic_gap_stable_seconds':0.0,
 'dynamic_gap_evidence_seconds':0.0,'min_clear_eta_seconds':1.1,'allow_clear_without_eta':False,
 'dynamic_gap_clear_hold_seconds':0.0,
}
i=StableRiskIndicator(cfg)
# First physical gap may signal.
a=i.update(2,False,eta=2.0,eta_source='dynamic-gap',external_gate_ok=True,
           required_eta_override=1.5,evidence_key='lane1|dynamic-gap|cycle7',now=1.0)
assert a['indicator_state']=='CLEAR',a
# Evidence drops and ends signal.
b=i.update(2,False,eta=2.0,eta_source='dynamic-gap',external_gate_ok=False,
           external_block_reason='flicker',required_eta_override=1.5,
           evidence_key='lane1|dynamic-gap|cycle7',now=1.1)
assert b['indicator_state']!='CLEAR',b
# Same physical gap must not re-signal.
c=i.update(2,False,eta=2.0,eta_source='dynamic-gap',external_gate_ok=True,
           required_eta_override=1.5,evidence_key='lane1|dynamic-gap|cycle7',now=1.2)
assert c['indicator_state']=='ETA HOLD',c
assert 'ALREADY SIGNALED' in c['clear_block_reason'],c
# New busy->clear cycle rearms.
d=i.update(2,False,eta=2.0,eta_source='dynamic-gap',external_gate_ok=True,
           required_eta_override=1.5,evidence_key='lane1|dynamic-gap|cycle8',now=1.3)
assert d['indicator_state']=='CLEAR',d

# Pending signal also blocks stacking in outcome tracker.
o=GreenJumpOutcomeTracker({'post_green_action_grace_seconds':0.75})
ch={'cx':100.0}
st={'indicator_state':'CLEAR','eta_source':'dynamic-gap','effective_eta':2.0,'raw_risk':2,'display_risk':2}
o.update(st,ch,1.0)
assert o.green_signals==1
st['indicator_state']='ETA HOLD'; o.update(st,ch,1.1)
assert o.pending_signal is not None
st['indicator_state']='CLEAR'; o.update(st,ch,1.2)
assert o.green_signals==1, o.status()
print('V4.4.8 signal dedup PASSED')
