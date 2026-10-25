import json, sys, tempfile, time, csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.adaptive import AdaptiveSessionModel
from app.safe_window import SafeWindowPredictor
from app.risk import RiskEngine
from app.learning import OnlineLearner

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Difficulty modes switch with hysteresis from live motion, not event pauses.
a=AdaptiveSessionModel(cfg['risk'])
base=time.time()+1.0
# EASY evidence: long gaps, low speed/density. Needs sustained easier dwell.
mp_easy={'support':30,'recent_support':18,'p25':2.6,'recent_p25':2.7,'gap_cv':.25,'busy_fraction':.08}
for i in range(30):
    m=a.update_difficulty_mode(base+i*.3,mp_easy,.10,.05,{'gap_p25':2.6})
assert m['mode']=='EASY',m
sw0=m['switches']
# HARD/EXTREME evidence should switch faster.
mp_hard={'support':30,'recent_support':18,'p25':.85,'recent_p25':.78,'gap_cv':.95,'busy_fraction':.62}
for i in range(24):
    m=a.update_difficulty_mode(base+8+i*.3,mp_hard,1.0,.9,{'gap_p25':.85})
assert m['mode'] in ('HARD','EXTREME'),m
assert m['switches']>sw0,m

# A traffic pause/new event after a long timestamp gap must NOT itself reset regime.
a2=AdaptiveSessionModel(cfg['risk'])
rid=a2.regime_id
now=time.time()+100
old=[{'ts':now-30,'token':'FT1','class':'F','speed':300,'gap':1.5}]
a2.last_processed_event_ts=now-60
a2.observe_traffic(old,now,75,155)
assert a2.regime_id==rid,(rid,a2.regime_id,a2.regime_reason)

# 2) Mode profile semantics: in HARD mode, low historical P25 can be accepted
# when the CURRENT verified gap is strong. Old global V5.4.3 P25>=2.20 blocked this.
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5'])
    state={
      'difficulty_mode':'HARD','dynamic_gap_ready':True,
      'dynamic_gap_preceding_busy_ok':True,'dynamic_gap_confidence':.78,
      'motion_gap_support':12,'motion_gap_p25':1.45,
      'dynamic_gap_action_lease':.36,'processing_fps':6.0,
      'dynamic_gap_lease_required':.08,'raw_risk':8.0,'risk':8.0,
      'motion_corridor_ratio':.0,'dynamic_gap_mog_global_ratio':.0,
    }
    assert sw._verified_gap_physical_ready(state,.95),state
    assert sw._verified_gap_physical_lease_requirement(state) <= .34,state
    # EXTREME needs stronger current evidence.
    x=dict(state); x['difficulty_mode']='EXTREME'; x['dynamic_gap_confidence']=.74
    assert not sw._verified_gap_physical_ready(x,.95),x
    # EASY can use a smaller presentation reserve.
    e=dict(state); e.update({'difficulty_mode':'EASY','motion_gap_p25':1.9,'dynamic_gap_confidence':.70,'motion_gap_support':9,'dynamic_gap_action_lease':.28})
    assert sw._verified_gap_physical_ready(e,.93),e
    # HARD/EXTREME cannot use sustained observed-clear shortcut.
    hard_obs={'difficulty_mode':'HARD'}
    assert not sw._sustained_observed_clear_ready(hard_obs,.99)
    sw._log_file.close()

# 3) RiskEngine exposes configured mode-specific dynamic thresholds.
r=RiskEngine(cfg['risk'])
assert r.mode_gap_min_support['EASY'] < r.mode_gap_min_support['EXTREME']
assert r.mode_gap_min_confidence['EASY'] < r.mode_gap_min_confidence['EXTREME']
assert r.mode_gap_quantile['EASY'] > r.mode_gap_quantile['EXTREME']
assert r.mode_recent_up_cap['EASY'] > r.mode_recent_up_cap['EXTREME']

# 4) State CSV schema remains aligned after added telemetry.
with tempfile.TemporaryDirectory() as td:
    root=Path(td); sess=root/'sessions'; sess.mkdir(parents=True)
    l=OnlineLearner(sess,{})
    l.log_state({},None,[],crash_event=None)
    l.flush(save_model=False)
    p=next(sess.glob('state_*.csv'))
    with p.open(newline='') as f:
        rr=csv.reader(f); h=next(rr); row=next(rr)
    assert len(h)==len(row),(len(h),len(row))

print('PASS V5.4.4 hysteretic difficulty modes + mode-aware gap profiles + schema')
