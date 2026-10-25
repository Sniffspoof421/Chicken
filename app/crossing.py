"""Independent raw occupancy of the landing/collision strip, including tails."""
import numpy as np


def crossing_bounds(lane_x, chicken, engine):
    """Full-frame rectangle shared by capture planning and occupancy checking."""
    half_y = engine.crossing_half_height + max(18., float(chicken.get('h', 60.))*.31)
    half_x = max(20., engine.lane_visibility_half_width)
    return (int(np.floor(float(lane_x)-half_x)),
            int(np.floor(float(chicken['cy'])-half_y)),
            int(np.ceil(float(lane_x)+half_x)),
            int(np.ceil(float(chicken['cy'])+half_y)))


def crossing_occupancy(motion_mask, lane_x, chicken, engine):
    result = dict(crossing_motion_available=False, crossing_motion_clear=False,
                  crossing_motion_ratio=1., crossing_motion_reason='NO CROSSING MASK')
    if chicken is None or lane_x is None or motion_mask is None:
        return result
    if isinstance(motion_mask, dict):
        mask = motion_mask.get('mask')
        x0, y0 = int(motion_mask.get('x0', 0)), int(motion_mask.get('y0', 0))
        if not motion_mask.get('ready', True):
            return result
    else:
        mask = motion_mask
        x0 = y0 = 0
    if mask is None or mask.size == 0:
        return result
    bx1, by1, bx2, by2 = crossing_bounds(lane_x, chicken, engine)
    x1, y1, x2, y2 = bx1-x0, by1-y0, bx2-x0, by2-y0
    # A cropped-away tail is unknown, never evidence of an empty crossing.
    if x1 < 0 or y1 < 0 or x2 > mask.shape[1] or y2 > mask.shape[0]:
        result['crossing_motion_reason'] = 'CROSSING ROI INCOMPLETE'
        return result
    region = mask[y1:y2, x1:x2]
    ratio = float(np.count_nonzero(region))/region.size
    clear = ratio <= engine.precision_czn_motion_ratio_max
    result.update(crossing_motion_available=True, crossing_motion_clear=clear,
                  crossing_motion_ratio=ratio,
                  crossing_motion_reason='' if clear else 'CROSSING OCCUPIED')
    return result


def apply_crossing_guard(state):
    if 'crossing_motion_available' not in state:
        return state
    if not state['crossing_motion_available'] or not state['crossing_motion_clear']:
        state['green_evidence_ok'] = False
        state['green_evidence_reason'] = state.get('crossing_motion_reason') or 'CROSSING OCCUPIED'
    return state
