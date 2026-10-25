import json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.safe_window import SafeWindowPredictor

cfg=json.loads((ROOT/'config.json').read_text())
with tempfile.TemporaryDirectory() as td:
    r=Path(td); (r/'data/models').mkdir(parents=True); (r/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(r,cfg['safe_window_v5'])
    sw.n=max(sw.min_samples,100); sw.fitted=True
    sw._predict=lambda s,x:(.98,'test')
    sw._threshold=lambda s:.90
    sw._heuristic_probability=lambda s:.98
    sw.last_heuristic_probability=.98

    # Reproduce V5.5.0 signal 19: strong-looking verified gap, but it opened
    # only ~0.27 s after a direct high-risk/visible threat. That was a tiny
    # interval between adjacent cars, not a mature traffic gap.
    base={
      'lane':1,'difficulty_mode':'EASY',
      'processing_healthy':True,'sensor_desync':False,'tracking_rewarm':False,
      'viewport_hold':False,'vision_hold':False,'target_green_geometry_ok':True,
      'motion_ready':True,'dynamic_gap_ready':True,'gap_open_ready':False,
      'dynamic_gap_cycle_id':19,'dynamic_gap_preceding_busy_ok':True,
      'dynamic_gap_confidence':.97,'dynamic_gap_action_lease':.816,
      'dynamic_gap_lease_required':0.0,'dynamic_gap_mog_global_ratio':.002,
      'motion_live_ready':True,'czn_live_ready':True,
      'motion_preceding_busy_duration':.445,
      'motion_gap_support':41,'motion_gap_p25':2.18,
      'motion_corridor_ratio':0.0,'motion_corridor_clear':True,
      'motion_clear_dwell':.44,'motion_current_clear_elapsed':.44,
      'dynamic_gap_effective_clear_elapsed':.44,
      'active_tracks':3,'slow_after_guard_active':False,'visible_threat':False,
      'uncertain_incoming_count':0,'lane_visibility_ok':True,'lane_visibility_score':1.0,
      'raw_risk':6.3,'risk':6.3,'effective_eta':2.186,'clear_dwell':.13,
      'recent_threat_age':.273,
      'crash_memory_score':0.0,'crash_memory_matches':0,'dynamic_gap_slow_guard':0,
      'target_lane_switches':57,'viewport_rebase_count':0,'processing_fps':6.46,
      'stage_difficulty_score':.2,'live_speed_difficulty_score':.2,
      'live_density_difficulty_score':.2,'recent_green_reliability':.8,
      'recent_green_failures':0,'recent_green_successes':1,'adaptive_confidence':.9,
      'source_reliability':.9,'crash_memory_safe_similarity':1.0,'slow_after_gap_score':0.0,
    }
    # A measured empty crossing preserves the existing admission behavior.
    base.update(crossing_motion_available=True,crossing_motion_clear=True,
                crossing_motion_ratio=0.,crossing_motion_reason='')
    bad=sw.apply(dict(base),now=10.0)
    assert not bad['v5_decision'],bad
    assert bad['v5_hard_reason']=='THREAT TAIL SETTLE',bad
    assert not bad['v5_threat_tail_ready'],bad
    assert abs(bad['v5_threat_tail_settle_required']-.55)<1e-9,bad

    # Once the direct threat has genuinely cleared for >=0.55 s, the exact same
    # strong physical gap remains eligible. This is a narrow onset delay, not a
    # new global lease/ETA restriction.
    sw.pending.clear(); sw._commit_active=False; sw._commit_since=None
    sw._commit_started=None; sw._commit_last_good=None
    sw._verified_active_cycle=None; sw._verified_hold_until=0.0; sw._verified_hold_key=None
    good=dict(base); good['recent_threat_age']=.61; good['dynamic_gap_cycle_id']=20
    good['motion_current_clear_elapsed']=.61; good['motion_clear_dwell']=.61
    good['dynamic_gap_effective_clear_elapsed']=.61
    out=sw.apply(good,now=11.0)
    assert out['v5_threat_tail_ready'],out
    assert out['v5_hard_reason']!='THREAT TAIL SETTLE',out
    assert out['v5_decision'],out

    # The supplied successful EASY signal 18 had ~1.30 s since last threat and
    # must remain untouched by this guard.
    success_like=dict(good); success_like['recent_threat_age']=1.298
    assert sw._threat_tail_ready(success_like)
    sw._log_file.close()

print('PASS V5.5.1 blocks only immature convoy-tail gap onset and preserves mature verified gaps')
