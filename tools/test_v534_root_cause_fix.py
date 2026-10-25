import json, tempfile, time, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.risk import RiskEngine
from app.safe_window import SafeWindowPredictor

cfg=json.load(open(ROOT/'config.json'))
r=RiskEngine(cfg['risk'])
now=time.time()
r._czn_reset_at=now-20.0

# V5.3.3 failure: old p95~741 permanently maxed the live CZN reference to
# ~700+, making ~635 px of visible road <1.0 s ETA forever.
ctx=r._czn_speed_context(
    [], [], {'speed_p90':84.0}, 155.0, now,
    historical_event_count=1292, historical_speed_p95=741.0
)
assert ctx['speed_reference'] <= 482.01, ctx
assert ctx['speed_reference_source'] == 'LIVE+BOUNDED_HISTORY', ctx
assert ctx['historical_prior_applied'], ctx

# After more than one piece of live evidence, history is no longer allowed to
# be the hard max for physical ETA.
r._raw_track_samples[1].append((now,120.0)); r._raw_track_samples[1].append((now,125.0))
r._raw_track_samples[2].append((now,140.0)); r._raw_track_samples[2].append((now,145.0))
ctx2=r._czn_speed_context(
    [], [], {'speed_p90':84.0}, 155.0, now+.01,
    historical_event_count=1292, historical_speed_p95=741.0
)
assert ctx2['live_speed_support'] >= 2, ctx2
assert ctx2['speed_reference_source'] == 'LIVE', ctx2
assert abs(ctx2['speed_reference']-392.0) < 1e-6, ctx2

with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    s=SafeWindowPredictor(root,cfg['safe_window_v5'])
    strong={
        'active_tracks':0,'dynamic_gap_ready':False,'gap_open_ready':False,
        'motion_live_ready':True,'czn_live_ready':False,
        'dynamic_gap_preceding_busy_ok':True,
        'motion_preceding_busy_duration':.55,
        'motion_gap_support':18,'motion_gap_p25':1.75,
        'motion_corridor_ratio':0.0,'dynamic_gap_mog_global_ratio':0.0,
    }
    assert s._live_gap_verified(strong), 'strong motion gap must bootstrap without CZN'
    weak=dict(strong); weak['motion_gap_support']=9; weak['motion_gap_p25']=1.10
    assert not s._live_gap_verified(weak), 'weak motion history must still wait for CZN/live proof'
    weak['czn_live_ready']=True
    assert s._live_gap_verified(weak), 'ordinary verified motion gap is valid once CZN is live'
    s._log_file.close()

print('PASS v534 current-session CZN speed authority + strong motion bootstrap')
