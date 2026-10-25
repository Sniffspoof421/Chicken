import sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.learning import OnlineLearner

cfg={
 'speed_min_calibration_events':12,'speed_slow_percentile':35,
 'speed_fast_percentile':70,'speed_min_band_px_s':22,
 'speed_fallback_slow_px_s':75,'speed_fallback_fast_px_s':155,
 'min_pattern_support':2,'max_pattern_order':4,
 'late_green_causal_max_seconds':2.2,
}
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td),cfg)
    # Isolate this regression from any legacy model auto-load fixture.
    l.green_failure_n=0
    l.green_source_failures.clear()
    l.green_source_failure_etas.clear()
    attempt={
        'late_after_green':True,
        'late_green_delay':1.05,
        'late_green_source':'dynamic-gap',
        'late_green_lane':1,
        'late_green_eta':1.92,
    }
    assert l.record_causal_late_green_failure(attempt,timestamp=100.0)==1
    assert l.green_failure_n==1
    assert l.green_source_failures['dynamic-gap']==1
    assert l.green_source_failures['dynamic-gap|L1']==1
    assert list(l.green_source_failure_etas['dynamic-gap'])[-1]==1.92
    floor=l.source_failure_eta_floor('dynamic-gap',base=1.58)
    assert floor>1.92, floor
    # Too-late/unrelated actions remain excluded.
    attempt['late_green_delay']=3.0
    assert l.record_causal_late_green_failure(attempt,timestamp=101.0)==0
    assert l.green_source_failures['dynamic-gap']==1
print('V4.4.11 causal late GREEN failure learning PASSED')
