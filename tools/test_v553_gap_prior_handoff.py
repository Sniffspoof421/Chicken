import json, sys, tempfile, csv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.risk import RiskEngine
from app.learning import OnlineLearner
from app.outcome import GreenJumpOutcomeTracker

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Session gap prior survives geometry reanchor, local history does not.
r=RiskEngine(cfg['risk'])
def step(lane, clear, t):
    return r._update_live_motion_profile(
        lane,
        {'available':True,'clear':bool(clear),'mog_global_ratio':0.0},
        float(t)
    )

t=1000.0
step(1,False,t)
for i in range(10):
    t+=.40; step(1,True,t)
    t+=2.05; prof=step(1,False,t)

assert prof['support']>=10,prof
assert prof['session_prior_support']>=10,prof

r.notify_geometry_reanchor()
t+=.20
prof=step(2,False,t)
assert prof['support']==0,prof
assert prof['session_prior_support']>=10,prof

for i in range(5):
    t+=.40; step(2,True,t)
    t+=2.10; prof=step(2,False,t)

assert prof['support']==5,prof
assert prof['recent_support']==5,prof
assert prof['session_prior_support']>=15,prof
assert prof['p25']>1.9,prof
assert prof['session_prior_p25']>1.9,prof

# 2) Mature V5.5.2 support thresholds stay unchanged.
risk=cfg['risk']
assert risk['mode_easy_gap_min_support']==8
assert risk['mode_normal_gap_min_support']==9
assert risk['mode_hard_gap_min_support']==10
assert risk['mode_extreme_gap_min_support']==12
assert risk['mode_normal_bootstrap_min_support']==5
assert risk['mode_hard_bootstrap_min_support']==6
assert risk['mode_extreme_bootstrap_min_support']==7
assert risk['dynamic_gap_bootstrap_min_margin_seconds']>=.30

# 3) Geometry-based rearm release: changing screen X must not pin RECHECK if
# current geometry proves the chicken is landed and target is valid.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.rearm_needed=True
o.rearm_x=190.0
state={
    'chicken_fresh':True,
    'chicken_anchor_stable':True,
    'target_lane_geometry_ok':True,
    'tracking_rewarm':False,
    'target_lane_distance_ratio':1.0,
    'target_lane_lock_reason':'HOLD_SAME',
    'target_lane_switches':5,
    'viewport_rebase_count':0,
}
o._update_rearm({'cx':630.0},20.0,state)
assert o.rearm_needed
o._update_rearm({'cx':1070.0},20.31,state)
assert not o.rearm_needed,o.status()
assert o.rearm_geometry_releases==1,o.status()

# 4) State CSV schema aligned.
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
    l.log_state({
        'dynamic_gap_session_prior_support':15,
        'dynamic_gap_session_prior_lower_bound':2.0,
        'dynamic_gap_bootstrap_candidate':1,
        'dynamic_gap_bootstrap_active':1,
        'dynamic_gap_bootstrap_lower_bound':2.0,
        'dynamic_gap_bootstrap_min_local_support':5,
        'landing_wait_age':1.5,
        'landing_wait_watchdog_recoveries':1,
        'landing_wait_watchdog_recovered':1,
        'green_rearm_geometry_releases':1,
    },None,[],None)
    l.flush(save_model=False)
    p=next((Path(td)/'sessions').glob('state_*.csv'))
    with p.open(newline='') as f:
        rr=csv.reader(f); h=next(rr); row=next(rr)
    assert len(h)==len(row),(len(h),len(row))
    for name in (
        'dynamic_gap_session_prior_support',
        'dynamic_gap_bootstrap_active',
        'dynamic_gap_bootstrap_lower_bound',
        'landing_wait_watchdog_recoveries',
        'green_rearm_geometry_releases'
    ):
        assert name in h,name

print('PASS V5.5.3 gap prior bootstrap + geometry rearm release + schema')
