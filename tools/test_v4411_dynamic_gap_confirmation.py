import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.indicator import StableRiskIndicator
root=Path(__file__).resolve().parents[1]
cfg=json.load(open(root/'config.json'))['indicator']
i=StableRiskIndicator(cfg)
i.update(95,eta=.2,eta_source='visible',external_gate_ok=False,now=1.0)
x=i.update(2,eta=2.0,eta_source='dynamic-gap',external_gate_ok=True,required_eta_override=1.58,evidence_key='L1|dynamic-gap|7',now=1.16)
assert not x['green_confirmed'],x
y=i.update(2,eta=1.95,eta_source='dynamic-gap',external_gate_ok=True,required_eta_override=1.58,evidence_key='L1|dynamic-gap|7',now=1.30)
assert y['green_confirmed'],y
print('V4.4.11 dynamic-gap two-frame confirmation PASSED')
