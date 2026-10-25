from app.indicator import StableRiskIndicator

cfg = {
    'green_threshold':24,'green_exit_threshold':38,'yellow_threshold':45,
    'red_threshold':72,'stable_low_seconds':0.65,'evidence_stable_seconds':0.9,
    'min_clear_eta_seconds':1.25,'allow_clear_without_eta':False,
    'dynamic_gap_stable_seconds':0.0,'dynamic_gap_evidence_seconds':0.0,
}
i = StableRiskIndicator(cfg)
# Reproduce the real V5.0 failure signature: V5 approves an ETA around 1.28s,
# while the old V4 learned requirement is ~1.56s. V5.0 accidentally reused
# that old requirement and showed no GREEN. V5.0.1 must honor V5 physical min.
r = i.update(35.0, visible_threat=False, eta=1.28, eta_source='v5-safe-window',
             external_gate_ok=True, required_eta_override=0.92,
             evidence_key='v5-cycle-1', now=100.0)
assert r['green_confirmed'], r
assert r['indicator_state'] == 'CLEAR', r
# Hard physical floor still blocks.
r2 = i.update(10.0, visible_threat=False, eta=0.80, eta_source='v5-safe-window',
              external_gate_ok=True, required_eta_override=0.92,
              evidence_key='v5-cycle-2', now=101.0)
assert not r2['green_confirmed'], r2
print('PASS v5.0.1 indicator handoff')
