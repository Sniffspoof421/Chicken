
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.learning import OnlineLearner

cfg={
 'speed_min_calibration_events':12,'speed_slow_percentile':35,
 'speed_fast_percentile':70,'speed_min_band_px_s':22,
 'speed_fallback_slow_px_s':75,'speed_fallback_fast_px_s':155,
 'min_pattern_support':2,'max_pattern_order':4,
}
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td),cfg)
    ts=0.0
    for i in range(8):
        l.events[0].append({'ts':ts,'class':'S','type':0,'token':'S',
                            'gap':1.0,'speed':25,'segment':0})
        ts+=1.0
        cls='F' if i==7 else 'M'
        gap=1.35+0.05*i
        l.events[0].append({'ts':ts,'class':cls,'type':0,'token':cls,
                            'gap':gap,'speed':80 if cls=='F' else 45,'segment':0})
        ts+=gap
    p=l.slow_anchor_profile(0,min_lane_support=6)
    assert p['ready'],p
    assert p['support']>=8,p
    assert p['p_fast_after_slow']<=.20,p
    assert p['p25_gap']>=1.35,p
print("V4.3.5 slow-anchor profile test PASSED")
