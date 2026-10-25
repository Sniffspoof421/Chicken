import json, sys, tempfile, csv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.safe_window import SafeWindowPredictor
from app.outcome import GreenJumpOutcomeTracker
from app.learning import OnlineLearner

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Exact V5.5.1 degraded-FPS failure profile:
# 2.3415 FPS => base frame margin ~0.467 s.
# V5.5.1 lease was ~0.4785, only ~11 ms above it.
# V5.5.2 adds .08 ONLY while degraded, so this must no longer qualify.
with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(root,cfg['safe_window_v5'])
    bad={
        'difficulty_mode':'NORMAL',
        'processing_fps':2.3415259401223545,
        'processing_degraded':1,
        'dynamic_gap_lease_required':0.0,
    }
    req=sw._verified_gap_physical_lease_requirement(bad)
    assert .54 < req < .56,req
    assert 0.4785025468499322 < req

    # A stronger low-FPS gap from the same V5.5.1 session remains usable.
    assert 0.7261040316445486 > req

    # Normal FPS remains V5.5.1/V5.4.7 behavior; no extra headroom.
    normal={
        'difficulty_mode':'NORMAL',
        'processing_fps':6.5,
        'processing_degraded':0,
        'dynamic_gap_lease_required':0.0,
    }
    req_normal=sw._verified_gap_physical_lease_requirement(normal)
    assert abs(req_normal-.22)<1e-9,req_normal
    sw._log_file.close()

# 2) Low-FPS hidden animation: GREEN at x~632, forward landing frame is missed,
# then exact target switch + VIEW_SCROLL reappears at x~189. This is positive
# progress evidence and must become an acted GREEN, never remain "unacted".
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base={
    'indicator_state':'CLEAR','green_confirmed':True,'lane':3,
    'eta_source':'v5-safe-window','v5_gap_provenance':'verified-gap',
    'effective_eta':1.99,'raw_risk':2.0,'display_risk':2.0,
    'target_lane_distance':440.0,'target_lane_x':1072.0,
    'target_lane_switches':17,'target_lane_lock_reason':'HOLD_SAME',
    'viewport_rebase_count':0,'chicken_fresh':True,
    'dynamic_gap_cycle_id':50,
}
o.update(base,{'cx':632.0,'detected':True},100.0)
off=dict(base); off['indicator_state']='WAIT'
o.update(off,{'cx':632.0,'detected':True},100.5)

# No forward animation is sampled. Signal becomes timing-only tombstone.
o.update(off,{'cx':632.0,'detected':True},102.9)
assert o.acted_signals==0

# At +3.15 s, geometry suggests progress with target switch +
# VIEW_SCROLL, and chicken reappears at first visible lane.
scroll=dict(off)
scroll.update({
    'target_lane_switches':18,
    'target_lane_lock_reason':'VIEW_SCROLL',
    'target_lane_x':631.0,
    'chicken_fresh':True,
})
ev=o.update(scroll,{'cx':189.0,'detected':True},103.15)
assert any(x.get('kind')=='action_started' and x.get('attribution')=='progress_handoff' for x in ev),ev
assert o.acted_signals==1,o.status()
assert o.progress_handoffs==1,o.status()
assert o.provisional is not None
assert o.provisional.get('landing_source')=='progress_scroll_handoff'

# It must not instantly call success; survival is still required.
ev=o.update(scroll,{'cx':190.0,'detected':True},103.50)
assert not any(x.get('outcome')=='success' for x in ev),ev

# Stable coordinates alone remain ambiguous; no SAFE label.
ev=o.update(scroll,{'cx':190.0,'detected':True},103.95)
succ=[x for x in ev if x.get('outcome')=='unknown']
assert succ,succ
assert succ[0].get('synthetic_progress_handoff') is True
assert o.successes==0

# 3) Synthetic progress handoff must NOT pollute reaction-time learning.
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
    before=len(l.green_source_action_delays['dynamic-gap'])
    out=dict(succ[0])
    out['timing_source']='dynamic-gap'
    out['features']=[0.0]*18
    out['safety_context']={}
    out['action_start_ts']=103.15
    out['start_ts']=100.0
    out['outcome_ts']=103.95
    l.record_green_outcome(out)
    after=len(l.green_source_action_delays['dynamic-gap'])
    assert after==before,(before,after)

# 4) State CSV schema aligned with new telemetry.
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
    l.log_state({
        'green_progress_handoffs':1,
        'v5_degraded_lease_headroom':.08,
        'v5_degraded_frame_margin':.547,
    },None,[],None)
    l.flush(save_model=False)
    p=next((Path(td)/'sessions').glob('state_*.csv'))
    with p.open(newline='') as f:
        r=csv.reader(f); h=next(r); row=next(r)
    assert len(h)==len(row),(len(h),len(row))
    for name in ('green_progress_handoffs','v5_degraded_lease_headroom','v5_degraded_frame_margin'):
        assert name in h,name

print('PASS V5.5.2 degraded-FPS headroom + hidden progress handoff + timing isolation')
