"""Replay recorded coordinate/ownership evidence; this is not video validation."""
import csv
import json
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app.outcome import GreenJumpOutcomeTracker
cfg = json.loads((root/'config.json').read_text())
upload = Path(sys.argv[1])
rows = list(csv.DictReader((upload/'state_20261022_052111.csv').open()))
audit = [json.loads(s) for s in (upload/'signal_audit_v558(1).jsonl').open()]
for signal_id in (4, 7):
    start = next(e for e in audit if e.get('signal_id')==signal_id
                 and e.get('kind')=='green_signal_started')
    action = next(e for e in audit if e.get('signal_id')==signal_id
                  and e.get('kind')=='action_started')
    initial = min(rows, key=lambda r:abs(float(r['timestamp'])-start['event_ts']))
    o = GreenJumpOutcomeTracker(cfg['outcome_learning'])
    baseline = float(initial['chicken_x'])
    o.active_attempt = dict(signal_id=signal_id, baseline_x=baseline,
        baseline_y=float(initial['chicken_y']), start_ts=start['event_ts'],
        action_start_ts=action['event_ts'], end_ts=action['event_ts'],
        action_start_x=action['chicken_x'], last_x=action['chicken_x'],
        max_x=action['chicken_x'], expected_jump_px=float(initial['target_lane_distance']),
        target_lane_x_at_signal=float(initial['target_lane_x']),
        target_switches_at_signal=int(initial['target_lane_switches']),
        viewport_rebase_at_signal=0, stable_since=None)
    outcomes = []
    for row in rows:
        now = float(row['timestamp'])
        if not action['event_ts'] <= now <= action['event_ts']+1.5:
            continue
        state = dict(target_lane_switches=int(row['target_lane_switches']),
                     viewport_rebase_count=0, chicken_fresh=row['chicken_fresh']=='1')
        chicken = (dict(cx=float(row['chicken_x']), cy=float(row['chicken_y']), detected=True)
                   if state['chicken_fresh'] else None)
        final = o._target_arrival_success(state, chicken, now)
        if final:
            outcomes.append(final)
        else:
            outcomes += o._attempt_progress(chicken, now)
            outcomes += o._provisional_progress(chicken, now)
    assert not any(e.get('outcome')=='success' for e in outcomes), outcomes
    assert any(e.get('outcome')=='failure' for e in outcomes), outcomes
    print('PASS recorded signal', signal_id, 'now retains regression outcome instead of premature success')
