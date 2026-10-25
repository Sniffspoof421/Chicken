from app.indicator import StableRiskIndicator

cfg={
    'green_threshold':24,'green_exit_threshold':38,'yellow_threshold':45,'red_threshold':72,
    'stable_low_seconds':0.0,'evidence_stable_seconds':0.0,
    'min_clear_eta_seconds':1.08,'clear_hold_seconds':0.0,
    'dynamic_gap_stable_seconds':0.0,'dynamic_gap_evidence_seconds':0.0,
    'dynamic_gap_clear_hold_seconds':0.0,
}
i=StableRiskIndicator(cfg)
# V5 committed signal stays CLEAR across frames; a soft external dropout must not
# permanently consume the gap inside the legacy dynamic-gap dedup mechanism.
a=i.update(10,False,eta=1.40,eta_source='v5-safe-window',external_gate_ok=True,
           required_eta_override=1.08,evidence_key='v5:7',now=1.0)
assert a['indicator_state']=='CLEAR',a
b=i.update(10,False,eta=1.40,eta_source='v5-safe-window',external_gate_ok=False,
           external_block_reason='RECHECK',required_eta_override=1.08,evidence_key='v5:7',now=1.1)
assert b['indicator_state']=='CHECKING',b
c=i.update(10,False,eta=1.40,eta_source='v5-safe-window',external_gate_ok=True,
           required_eta_override=1.08,evidence_key='v5:7',now=1.2)
assert c['indicator_state']=='CLEAR',c
assert 'ALREADY SIGNALED' not in c.get('clear_block_reason',''),c

# Legacy dynamic-gap remains one-shot.
j=StableRiskIndicator(cfg)
d=j.update(10,False,eta=1.40,eta_source='dynamic-gap',external_gate_ok=True,
           required_eta_override=1.08,evidence_key='dg:3',now=2.0)
assert d['indicator_state']=='CLEAR',d
j.update(10,False,eta=1.40,eta_source='dynamic-gap',external_gate_ok=False,
         external_block_reason='DROP',required_eta_override=1.08,evidence_key='dg:3',now=2.1)
e=j.update(10,False,eta=1.40,eta_source='dynamic-gap',external_gate_ok=True,
           required_eta_override=1.08,evidence_key='dg:3',now=2.2)
assert e['indicator_state']=='ETA HOLD' and 'ALREADY SIGNALED' in e['clear_block_reason'],e
print('PASS v524 V5 display continuity / dynamic-gap dedup separation')
