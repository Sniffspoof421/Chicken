import json, sys, tempfile, csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.safe_window import SafeWindowPredictor
from app.learning import OnlineLearner

cfg=json.loads((ROOT/'config.json').read_text())

# 1) V5.4.7 decision profiles are preserved exactly.
with tempfile.TemporaryDirectory() as td:
    root=Path(td); (root/'data/models').mkdir(parents=True); (root/'data/sessions').mkdir(parents=True)
    sw=SafeWindowPredictor(root,cfg['safe_window_v5'])
    assert abs(sw.mode_verified_profiles['EASY']['physical_lease']-.18)<1e-9
    assert abs(sw.mode_verified_profiles['NORMAL']['physical_lease']-.22)<1e-9
    assert abs(sw.mode_verified_profiles['HARD']['physical_lease']-.26)<1e-9
    assert abs(sw.mode_verified_profiles['EXTREME']['physical_lease']-.30)<1e-9
    assert abs(sw.mode_verified_profiles['EASY']['standard_lease']-.34)<1e-9
    assert abs(sw.mode_verified_profiles['NORMAL']['standard_lease']-.42)<1e-9
    assert abs(sw.mode_verified_profiles['HARD']['standard_lease']-.46)<1e-9
    assert abs(sw.mode_verified_profiles['EXTREME']['standard_lease']-.50)<1e-9

    # Low FPS is made safe by the existing frame-margin rule rather than a
    # blanket processing veto: at 2.35 FPS reserve is about 0.466 s.
    state={'difficulty_mode':'NORMAL','processing_fps':2.35,'dynamic_gap_lease_required':0.0}
    req=sw._verified_gap_physical_lease_requirement(state)
    assert .46 <= req <= .48,req
    sw._log_file.close()

# 2) V5.4.9 config keeps normal threshold for telemetry but allows a stable
# degraded mode down to 2.0 FPS.
assert abs(cfg['risk']['min_processing_fps_for_green']-2.8)<1e-9
assert abs(cfg['risk']['degraded_min_processing_fps_for_green']-2.0)<1e-9

# 3) Manual success is supplemental, not required for model operation.
assert cfg['learning']['passive_manual_success_enabled'] is True

# 4) State CSV schema remains aligned with new degraded/recovery telemetry.
with tempfile.TemporaryDirectory() as td:
    l=OnlineLearner(Path(td)/'sessions',cfg['learning'])
    state={
        'processing_fps':2.35,'processing_lag_ms':425.0,
        'processing_healthy':True,'processing_degraded':1,
        'processing_green_floor_fps':2.0,
        'forced_chicken_reacquires':2,
        'post_jump_reacquire_active':1,
        'post_jump_reacquire_age_required':.60,
        'chicken_fresh_age':.7,
    }
    l.log_state(state,None,[],None)
    l.flush(save_model=False)
    p=next((Path(td)/'sessions').glob('state_*.csv'))
    with p.open(newline='') as f:
        r=csv.reader(f); h=next(r); row=next(r)
    assert len(h)==len(row),(len(h),len(row))
    for name in (
        'processing_degraded','processing_green_floor_fps',
        'post_jump_reacquire_active','post_jump_reacquire_age_required',
        'manual_success_duplicate_skips','last_manual_success_switch',
        'manual_success_context_only'
    ):
        assert name in h,name

print('PASS V5.4.9 preserves V5.4.7 GREEN logic + degraded FPS safety + telemetry')
