import json, sys, tempfile, csv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.chicken import ChickenDetector
from app.outcome import GreenJumpOutcomeTracker
from app.risk import RiskEngine
from app.learning import OnlineLearner

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Safety input response is explicitly separate from CV-confirmation latency.
r=RiskEngine(cfg['risk'])
assert abs(r.cfg_input_reaction_easy-.30)<1e-9
assert abs(r.cfg_input_reaction_normal-.34)<1e-9
assert abs(r.cfg_input_reaction_hard-.40)<1e-9
assert abs(r.cfg_input_reaction_extreme-.46)<1e-9

# 2) A real GREEN jump remains attributable while generic motion/ROI rewarm is
# active. Only an actual coordinate-frame move/reframe may suppress ownership.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
base={
    'indicator_state':'CLEAR','green_confirmed':True,'lane':1,
    'eta_source':'v5-safe-window','v5_gap_provenance':'verified-gap',
    'effective_eta':2.2,'raw_risk':2.0,'display_risk':2.0,
    'target_lane_distance':440.0,'target_lane_x':630.0,
    'target_lane_switches':1,'target_lane_lock_reason':'HOLD_SAME',
    'viewport_rebase_count':0,'chicken_fresh':True,
    'scene_pan_active':False,'game_progress_scroll_active':False,
    'game_progress_scroll_settling':False,'fullscreen_reframe_active':False,
}
o.update(base,{'cx':190.0,'detected':True},10.0)
off=dict(base); off['indicator_state']='WAIT'
off['viewport_hold']=True
off['vision_hold']=True
off['tracking_rewarm']=True
o.update(off,{'cx':190.0,'detected':True},10.30)
ev=o.update(off,{'cx':315.0,'detected':True},11.30)
started=[x for x in ev if x.get('kind')=='action_started']
assert started,ev
assert o.acted_signals==1,o.status()

# Real fullscreen reframe still blocks action attribution.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.update(base,{'cx':190.0,'detected':True},20.0)
off2=dict(off); off2['fullscreen_reframe_active']=True
o.update(off2,{'cx':190.0,'detected':True},20.25)
ev=o.update(off2,{'cx':320.0,'detected':True},21.0)
assert not any(x.get('kind')=='action_started' for x in ev),ev

# 3) Ambiguous ~0.4-lane colour drift is held, not accepted as chicken.
cd=ChickenDetector(cfg['chicken'])
cd.set_lane_spacing(440.0)
cd.last={
    'cx':630.0,'cy':700.0,'w':100.0,'h':100.0,
    'x':580.0,'y':650.0,'detected':True,'confidence':.9,'geom_scale':1.0
}
mid={
    'cx':460.0,'cy':700.0,'w':100.0,'h':100.0,
    'x':410.0,'y':650.0,'detected':True,'confidence':.9,'geom_scale':1.0
}
out=cd._confirm_candidate(dict(mid))
assert out.get('pending_position'),out
assert out.get('midlane_rejected'),out
assert abs(out['cx']-630.0)<1e-6,out
assert cd.midlane_rejections==1

# A real one-lane landing is still confirmable after the configured frames.
land={
    'cx':1070.0,'cy':700.0,'w':100.0,'h':100.0,
    'x':1020.0,'y':650.0,'detected':True,'confidence':.9,'geom_scale':1.0
}
accepted=None
for _ in range(cfg['chicken']['jump_confirm_frames']):
    accepted=cd._confirm_candidate(dict(land))
assert accepted and abs(accepted['cx']-1070.0)<5.0,accepted
assert not accepted.get('pending_position',False),accepted

# 4) State CSV schema remains aligned after added recovery telemetry.
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
    state={
        'dynamic_gap_observed_action_delay':1.4,
        'chicken_candidate_count':2,
        'chicken_midlane_rejected':1,
        'chicken_midlane_rejections':3,
        'runtime_tick_gap_seconds':2.1,
        'runtime_gap_recoveries':1,
        'runtime_gap_recovery_active':1,
    }
    l.log_state(state,None,[],None)
    l.flush(save_model=False)
    p=next((Path(td)/'sessions').glob('state_*.csv'))
    with p.open(newline='') as f:
        rr=csv.reader(f); h=next(rr); row=next(rr)
    assert len(h)==len(row),(len(h),len(row))
    for name in (
        'dynamic_gap_observed_action_delay','chicken_candidate_count',
        'chicken_midlane_rejected','runtime_tick_gap_seconds',
        'runtime_gap_recoveries'
    ):
        assert name in h,name

print('PASS V5.4.7 click-vs-CV timing split + rewarm action ownership + midlane identity + telemetry')
