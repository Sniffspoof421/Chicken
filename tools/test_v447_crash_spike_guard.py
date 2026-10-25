import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.crash import CrashDetector

cfg={
 'reset_back_px':180,'min_progress_px':140,'reset_near_start_px':120,
 'confirm_frames':2,'reset_cluster_radius_px':90,'dedup_seconds':.1,
 'min_run_seconds':0.0,'initial_calibration_seconds':0.0,
 'max_forward_step_px':420,'max_forward_step_frame_fraction':.38,
}

def ch(x): return {'cx':float(x),'detected':True}

# Impossible right-edge colour teleport must not create progress/crash.
d=CrashDetector(cfg)
assert d.update(ch(190),2560,0.0) is None
assert d.update(ch(2407),2560,0.2) is None
assert d.forward_spikes_ignored==1
assert d.update(ch(191),2560,0.4) is None
assert d.crash_count==0
assert d.max_x < 300

# Real progressive motion followed by stable reset still emits a crash.
d=CrashDetector(cfg)
assert d.update(ch(190),2560,0.0) is None
assert d.update(ch(500),2560,0.2) is None
assert d.update(ch(700),2560,0.4) is None
assert d.update(ch(192),2560,0.6) is None
e=d.update(ch(194),2560,0.8)
assert e and e['crash'] and e['max_x']>=700,e
print('V4.4.7 crash spike guard PASSED')
