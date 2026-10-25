import sys,json,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.display_lease import deadline_for_state,expire_state,DisplayLease
cfg=json.loads((ROOT/'config.json').read_text())
base=dict(indicator_state='CLEAR',green_confirmed=True,lane=2,effective_eta=2.,
 target_lane_distance=440.,target_lane_x=1070.,target_lane_switches=45,
 viewport_rebase_count=0,chicken_fresh=True)
def signal():
 o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
 o.update(base,dict(cx=630.,detected=True),100.)
 o.update({**base,'indicator_state':'WAIT'},dict(cx=630.,detected=True),100.5)
 return o
scroll={**base,'indicator_state':'WAIT','target_lane_switches':46,
 'target_lane_lock_reason':'VIEW_SCROLL'}
# Valid progress handoff is preserved, but reset-in-progress cannot create one.
for flag in ('reset_candidate_pending','reset_confirmed_this_tick'):
 o=signal(); ev=o.update({**scroll,flag:1},dict(cx=190.,detected=True),102.)
 assert not any(e.get('attribution')=='progress_handoff' for e in ev),ev
 assert o.acted_signals==0
# Delayed reset confirmation must not resolve a newer synthetic attempt.
o=signal(); o.update(scroll,dict(cx=190.,detected=True),102.)
assert o.provisional is not None
x=o.on_crash(dict(event_time=101.85,reason='confirmed_progress_reset'),102.4)
assert x['outcome']=='unknown' and x['unknown_reason']=='reset_precedes_action',x
assert o.failures==0 and o.successes==0
assert o.on_crash(dict(event_time=101.85),102.5) is None
# Genuine action observed before reset still produces failure.
o=signal(); o.update({**base,'indicator_state':'WAIT'},dict(cx=800.,detected=True),100.7)
assert o.active_attempt is not None
x=o.on_crash(dict(event_time=101.,reason='confirmed_progress_reset'),101.2)
assert x['outcome']=='failure' and o.failures==1,x
# Deadline changes presentation only; no new ETA/support/lease minimum.
s=dict(indicator_state='CLEAR',v5_gap_provenance='verified-gap',
 v5_verified_gap_action_lease=.0022417524,green_evidence_ok=True)
d=deadline_for_state(s,100.)
s['green_display_deadline']=d
assert expire_state(s,d-.000001)['indicator_state']=='CLEAR'
x=expire_state(s,d)
assert x['indicator_state']=='ETA HOLD' and not x['green_confirmed']
assert s['indicator_state']=='CLEAR' # no mutation of analysis/UI snapshot
assert deadline_for_state({'v5_gap_provenance':'observed-clear'},100.) is None
# Timer closure retains exact expiry, not a later analysis timestamp.
o=signal();o.current_signal=o.pending_signal;o.pending_signal=None
o.expire_display(100.25)
assert o.current_signal is None and o.pending_signal['end_ts']==100.25
assert o.pending_signal['duration']==.25
latch=DisplayLease()
state=dict(v5_gap_provenance='verified-gap',v5_decision=True,
 v5_verified_gap_action_lease=.5,lane=1,target_lane_switches=1,
 viewport_rebase_count=0,dynamic_gap_cycle_id=10)
assert latch.update(state,100.)==100.5
assert latch.update({**state,'v5_verified_gap_action_lease':1.},100.2)==100.5
assert latch.update({**state,'v5_verified_gap_action_lease':.1},100.2)==100.3
assert latch.update({**state,'dynamic_gap_cycle_id':11},101.)==101.5
print('PASS V555 reset chronology, pending-reset handoff, genuine failures, exact display expiry')
# Optional read-only replay of supplied logs (not bundled with the program).
if len(sys.argv)>1:
 upload=Path(sys.argv[1])
 rows=list(csv.DictReader((upload/'state_20261021_220002.csv').open()))
 clear=[r for r in rows if r['indicator_state']=='CLEAR']
 assert len(clear)==26
 assert not any(int(r['upstream_prediction_available']) for r in clear)
 outcomes=list(csv.DictReader((upload/'green_outcomes_20261021_220002.csv').open()))
 bad=[r for r in outcomes if float(r['outcome_timestamp'])<float(r['action_start'])]
 assert len(bad)==1 and bad[0]['signal_id']=='14'
 # Replay exact impossible chronology through the patched tracker.
 r=bad[0];o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
 o.provisional={'signal_id':14,'action_start_ts':float(r['action_start']),
                'landing_source':'progress_scroll_handoff'}
 e=o.on_crash({'event_time':float(r['outcome_timestamp'])})
 assert e['outcome']=='unknown' and o.failures==0
 print('PASS supplied-log replay: 26 CLEAR rows without trajectories; signal 14 invalid chronology -> UNKNOWN')
