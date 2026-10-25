import json, tempfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.outcome import GreenJumpOutcomeTracker
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())

# 1) Expired GREEN must not remain a supervised crash permission for seconds.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.pending_signal={
    'signal_id':7,'start_ts':10.0,'end_ts':10.8,'duration':0.8,
    'baseline_x':630.0,'lane':2,'eta_source':'v5-safe-window','eta':1.6,
    'expected_jump_px':440.0,
}
# 0.80 s after GREEN ended: diagnostic late action only, no active attempt.
e=o._start_action_if_needed({'cx':660.0,'detected':True},11.60,state={'chicken_fresh':True})
assert e and e['kind']=='late_unattributed_action', e
assert o.active_attempt is None
assert o.acted_signals == 0

# 2) A near-immediate post-GREEN reaction can still be attributed.
o=GreenJumpOutcomeTracker(cfg['outcome_learning'])
o.pending_signal={
    'signal_id':8,'start_ts':20.0,'end_ts':20.8,'duration':0.8,
    'baseline_x':630.0,'lane':2,'eta_source':'v5-safe-window','eta':1.7,
    'expected_jump_px':440.0,
}
e=o._start_action_if_needed({'cx':660.0,'detected':True},21.30,state={'chicken_fresh':True})
assert e and e['kind']=='action_started', e
assert o.active_attempt is not None
assert 0.49 <= o.active_attempt['post_green_delay'] <= 0.51

# 3) Observed-clear is no longer allowed at the 1.08-1.43 s ETAs that failed
# every acted GREEN in the supplied run. Verified gap remains less strict.
with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(root,cfg['safe_window_v5'])
    obs=sw._required_eta_for_green({},'observed-clear',0.0)
    ver=sw._required_eta_for_green({},'verified-gap',0.0)
    fc=sw._required_eta_for_green({},'tracked-forecast',0.0)
    assert obs >= 1.58, obs
    assert ver >= 1.30, ver
    assert fc >= 1.58, fc
    sw._log_file.close()

print('PASS V5.3.6 expired-GREEN attribution + actionable ETA floors')
