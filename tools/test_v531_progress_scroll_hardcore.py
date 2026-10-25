from pathlib import Path
import tempfile, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.scene_motion import ProgressScrollGate
from app.indicator import required_eta_override_for_state
from app.safe_window import SafeWindowPredictor

# 1) Normal game auto-scroll: never authorize while pixels are moving, but do
# not inherit the raw detector's long hold tail after the scroll stops.
g=ProgressScrollGate({
    'game_auto_scroll_enabled':True,
    'progress_scroll_quiet_seconds':.22,
    'progress_scroll_context_seconds':.90,
})
a=g.update({'pan_active':True,'stable':False},10.0)
assert not a['effective_stable'] and a['progress_scroll_count']==1, a
b=g.update({'pan_active':False,'stable':False},10.10)
assert not b['effective_stable'] and b['progress_scroll_settling'], b
c=g.update({'pan_active':False,'stable':False},10.24)
assert c['effective_stable'] and c['progress_scroll_context'], c
# Another pan inside the same cluster does not create a new scroll cluster.
d=g.update({'pan_active':True,'stable':False},10.40)
assert d['progress_scroll_count']==1 and not d['effective_stable'], d
# A much later scroll is a new cluster.
e=g.update({'pan_active':True,'stable':False},11.50)
assert e['progress_scroll_count']==2, e

# 2) V5's provenance-aware ETA is authoritative at the final indicator. Legacy
# clear-zone still keeps its own learned requirement.
assert required_eta_override_for_state({
    'eta_source':'v5-safe-window','v5_required_eta':1.08,'green_required_eta':1.79
}) == 1.08
assert required_eta_override_for_state({
    'eta_source':'clear-zone','v5_required_eta':1.08,'green_required_eta':1.79
}) == 1.79

# 3) Sustained, physically clean observed-clear may outvote a stale classifier
# in hardcore traffic. Hard physical vetoes remain authoritative.
def state(prob=.50):
    return {
        'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
        'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
        'motion_ready':True,'visible_threat':False,'uncertain_incoming_count':0,
        'lane_visibility_ok':True,'lane_visibility_score':.99,
        'motion_corridor_ratio':.0,'motion_clear_dwell':1.4,
        'motion_current_clear_elapsed':1.25,'dynamic_gap_mog_global_ratio':.0,
        'raw_risk':2.0,'crash_memory_score':0.0,'crash_memory_matches':0,
        'dynamic_gap_slow_guard':0,'effective_eta':1.30,
        'stage_difficulty_score':.85,'live_speed_difficulty_score':.9,
        'live_density_difficulty_score':.6,'stage_gap_p25':.95,
        'motion_gap_support':30,'motion_gap_p25':1.35,
        'motion_live_ready':True,'czn_live_ready':True,
        'dynamic_gap_preceding_busy_ok':True,'motion_preceding_busy_duration':.5,
        'active_tracks':0,'dynamic_gap_ready':False,'gap_open_ready':False,
        'eta_source_reliability':.8,'adaptive_confidence':.8,
        'dynamic_gap_confidence':.6,'recent_green_reliability':.6,
        'recent_green_failures':0,'recent_green_successes':0,'clear_dwell':1.4,
        'lane':'1','chicken_fresh':True,'target_lane_switches':0,
        'viewport_rebase_count':0,'dynamic_gap_cycle_id':1,
        'green_evidence_ok':False,'green_evidence_reason':'',
        'slow_window_reason':'NO VERIFIED SLOW WINDOW',
        'slow_window_profile_support':20,'slow_window_profile_confidence':.9,
        'slow_window_p25_gap':1.5,'test_prob':prob,
    }

cfg={
    'enabled':True,'min_training_samples':0,'save_interval_seconds':99999,
    'absolute_min_eta_seconds':1.08,'verified_gap_min_eta_seconds':1.08,
    'observed_clear_min_eta_seconds':1.08,'forecast_min_eta_seconds':1.12,
    'min_live_gap_p25_seconds':.95,'min_live_gap_support':8,
    'min_preceding_busy_seconds':.16,'min_motion_clear_dwell_seconds':.3,
    'observed_clear_min_elapsed_seconds':.7,'observed_clear_min_gap_p25_seconds':1.1,
    'base_probability_threshold':.90,'easy_probability_threshold':.91,
    'hard_probability_threshold':.88,'adaptive_probability_floor':.885,
    'observed_clear_probability_floor_easy':.85,'observed_clear_probability_floor_hard':.79,
    'gap_difficulty_easy_seconds':1.55,'gap_difficulty_hard_seconds':.8,
    'speed_difficulty_weight':.72,'gap_difficulty_weight':.88,'density_difficulty_weight':.55,
    'green_commit_dwell_seconds':.32,'green_commit_hard_add_seconds':-.04,
    'green_commit_min_seconds':.28,'green_commit_max_seconds':.34,
    'observed_clear_physical_override_enabled':True,
    'observed_clear_physical_min_elapsed_seconds':1.0,
    'observed_clear_physical_min_gap_p25_seconds':1.05,
    'observed_clear_physical_eta_margin_seconds':.05,
    'observed_clear_physical_max_motion_ratio':.04,
    'observed_clear_physical_max_mog_ratio':.055,
    'observed_clear_physical_max_raw_risk':20.0,
    'observed_clear_physical_min_probability':.42,
    'observed_clear_physical_min_difficulty':.60,
}
with tempfile.TemporaryDirectory() as td:
    p=SafeWindowPredictor(Path(td),cfg); p.n=100
    p._maybe_add_candidate=lambda *a,**k:None
    p._update_pending=lambda *a,**k:''
    p._predict=lambda st,x:(float(st.get('test_prob',.50)),'test')
    s=state(.50)
    o=p.apply(dict(s),20.0)
    assert o['v5_gap_provenance']=='observed-clear',o
    assert o['v5_observed_clear_override'] and o['v5_physical_override'],o
    assert o['v5_raw_decision'],o
    req=o['v5_commit_required']
    o=p.apply(dict(s),20.0+req+.02)
    assert o['v5_decision'],o

    # Same probability with insufficient current physical clearance is blocked.
    p._commit_key=None; p._commit_since=None; p._commit_last_good=None; p._commit_active=False
    bad=state(.50); bad['motion_current_clear_elapsed']=.76; bad['dynamic_gap_cycle_id']=2
    o=p.apply(bad,30.0)
    assert not o['v5_raw_decision'] and not o['v5_observed_clear_override'],o

    # Real hazard still wins immediately.
    haz=state(.95); haz['visible_threat']=True; haz['dynamic_gap_cycle_id']=3
    p._commit_key=None; p._commit_since=None; p._commit_last_good=None; p._commit_active=False
    o=p.apply(haz,40.0)
    assert not o['v5_raw_decision'] and o['v5_hard_reason']=='VISIBLE THREAT',o
    p._log_file.close()

print('PASS v531 progress-scroll + V5 ETA handoff + sustained observed-clear override')
