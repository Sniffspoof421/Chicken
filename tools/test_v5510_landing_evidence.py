"""Physical landing evidence, ambiguous scrolls and early vehicle regression tests."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.risk import RiskEngine
from app.upstream import predict_arrival, apply_guard

cfg = json.loads((ROOT/'config.json').read_text())
base = dict(indicator_state='CLEAR', green_confirmed=True, lane=1,
            target_lane_distance=440., target_lane_x=630.,
            target_lane_switches=3, viewport_rebase_count=0, chicken_fresh=True)
land = dict(base, indicator_state='WAIT', green_confirmed=False,
            target_lane_switches=4, target_lane_x=1070.)

def attempt():
    o = GreenJumpOutcomeTracker(cfg['outcome_learning'])
    o.update(base, dict(cx=190., cy=731., detected=True), 10.)
    o.update(dict(base, indicator_state='WAIT', green_confirmed=False),
             dict(cx=320., cy=720., detected=True), 10.2)
    assert o.active_attempt is not None
    return o

# Signal 4's observed shape: reaches target in displaced-Y animation, resets.
o = attempt()
ev = o.update(land, dict(cx=642., cy=781., detected=True), 10.5)
assert not any(e.get('outcome')=='success' for e in ev), ev
ev = o.update(land, dict(cx=191., cy=731., detected=True), 10.8)
assert any(e.get('outcome')=='failure' for e in ev), ev
assert o.successes == 0

# A switch plus a held/missing frame is never a successful landing.
o = attempt()
for t in (10.5, 10.9):
    ev = o.update(dict(land, chicken_fresh=False), None, t)
    assert not any(e.get('outcome')=='success' for e in ev)

# A real settled landing is still terminal: later reset cannot overwrite it.
o = attempt()
all_events = []
for t in (10.5, 10.7, 10.9):
    all_events += o.update(land, dict(cx=632., cy=732., detected=True), t)
assert sum(e.get('outcome_state')=='SUCCESS_FINAL' for e in all_events)==1, all_events
assert o.on_crash(dict(reason='later_reset'), 11.3) is None
assert o.successes == 1 and o.failures == 0

# Coordinate-derived scroll ownership cannot create a SAFE training example.
o = GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.update(base, dict(cx=630., cy=731., detected=True), 20.)
scroll = dict(land, target_lane_lock_reason='VIEW_SCROLL')
ev = o.update(scroll, dict(cx=190., cy=731., detected=True), 20.3)
assert any(e.get('kind')=='action_started' for e in ev), ev
ev = o.update(scroll, dict(cx=190., cy=731., detected=True), 21.2)
assert any(e.get('outcome')=='unknown' for e in ev), ev
assert o.successes == 0

# Viewport cancellation has a durable UNKNOWN instead of losing the signal.
o = GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.update(base, dict(cx=190., cy=731., detected=True), 30.)
o.invalidate_unacted_viewport(now=30.4)
ev = o.update(dict(base, indicator_state='WAIT', green_confirmed=False), None, 30.5)
assert any(e.get('unknown_reason')=='viewport_change_without_observed_action'
           and e.get('training_eligible') is False for e in ev), ev

# Fast positive trajectory can veto on observation two, before direction lock.
class Mapper:
    def lane_for(self, x): return int(x//400)
r = RiskEngine(cfg['risk'])
track = dict(id=1, cx=610., cy=550., h=80., age=2,
             matched=True, direction_valid=False, ts=10.,
             history=[(9.84, 608., 430.), (10., 610., 550.)])
chicken = dict(cy=800., h=60.)
eta, tid = predict_arrival([track], chicken, 1, 610., Mapper(), r, 10.)
assert eta is not None and eta < .4, eta
assert apply_guard({'green_evidence_ok':True}, eta, tid, 1.4)['upstream_prediction_blocked']
for history in ([(10.,610.,550.)], [(9.84,610.,570.),(10.,610.,550.)],
                [(9.84,500.,430.),(10.,610.,550.)],
                [(9.,608.,430.),(10.,610.,550.)]):
    assert predict_arrival([dict(track, history=history)], chicken, 1, 610., Mapper(), r, 10.) == (None,None)
assert predict_arrival([dict(track, missing=1)], chicken, 1, 610., Mapper(), r, 10.) == (None,None)
print('PASS V5510 landing regression, terminal settled success, ambiguous scroll, cancellation audit, two-observation threat guard')
