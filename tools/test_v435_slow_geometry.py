
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.risk import RiskEngine

r=RiskEngine({
 'jump_crossing_seconds':.55,'safety_buffer_seconds':.30,
 'crossing_half_height_px':35,'min_approach_vy_px_s':12,
 'slow_window_enabled':True,'slow_window_min_profile_support':6,
 'slow_window_min_profile_confidence':.68,
 'slow_window_max_next_fast_prob':.35,
 'slow_window_min_p25_gap_seconds':.95,
 'slow_window_speed_margin':1.28,'slow_window_track_min_age':4,
 'slow_window_direction_consistency_min':.65,
 'slow_window_extra_margin_seconds':.12,
})
ch={'cx':100.0,'cy':700.0,'h':60.0}
slow_track={
 'id':10,'age':8,'cx':100.0,'cy':500.0,'h':30.0,
 'vy':28.0,'fit_vy':29.0,'net_vy':28.0,
 'direction_valid':True,'direction_consistency':.9
}
cand={'track':slow_track,'class':'S','entry':2.5,'tti':7.0,
      'clearance':1.5,'overlap':False,'speed':28}
l1={'candidates':[cand],'uncertain_incoming_count':0,'visible_threat':False}
profile={'ready':True,'support':20,'lane_support':20,'source':'lane',
         'p25_gap':1.4,'median_gap':2.2,'p_fast_after_slow':.15,
         'confidence':.85}
x=r._slow_window_geometry(
    l1=l1,chicken=ch,slow_thr=34,fast_thr=57,profile=profile,
    upstream_eta=1.5,motion_view={'available':True,'clear':False,'ratio':.1},
    motion_clear_dwell=0,stage_score=.2
)
assert x['ok'] and x['mode']=='slow-before',x

fast_track={
 'id':11,'age':8,'cx':100.0,'cy':430.0,'h':30.0,
 'vy':140.0,'fit_vy':140.0,'net_vy':140.0,
 'direction_valid':True,'direction_consistency':.9
}
fast={'track':fast_track,'class':'F','entry':1.0,'tti':1.8,
      'clearance':.4,'overlap':False,'speed':140}
l1b={'candidates':[cand,fast],'uncertain_incoming_count':0,'visible_threat':False}
y=r._slow_window_geometry(
    l1=l1b,chicken=ch,slow_thr=34,fast_thr=57,profile=profile,
    upstream_eta=1.5,motion_view={'available':True,'clear':False,'ratio':.1},
    motion_clear_dwell=0,stage_score=.2
)
assert not (y['ok'] and y['mode']=='slow-before'),y
print("V4.3.5 slow-before / fast-follower guard PASSED")
