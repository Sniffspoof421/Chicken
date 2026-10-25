"""Trajectory-only guard; no gap history, class priors or new admission floors."""
import math


def predict_arrival(tracks, chicken, lane_index, lane_x, mapper, engine, now):
    arrivals=[]
    if chicken is None:
        return None, None
    for t in tracks:
        missing = bool(t.get('missing',0) or not t.get('matched',True))
        if (mapper.lane_for(t['cx']) != lane_index
                and abs(float(t['cx'])-lane_x)>engine.lane_x_tolerance):
            continue
        mature = (int(t.get('age',0)) >= engine.min_track_age
                  and t.get('direction_valid',False)
                  and not t.get('direction_suspicious',False))
        if mature:
            speeds=[float(t.get(k,0.0)) for k in ('vy','fit_vy','net_vy')]
            if not all(math.isfinite(v) for v in speeds):
                continue
            speed=max(speeds)
        else:
            if missing:
                # Do not extrapolate an unconfirmed association through loss.
                continue
            # At low FPS a fast incoming vehicle can arrive before a third
            # observation establishes direction_valid. Two measured, same-lane
            # positions may veto GREEN, but never create GREEN or train a class.
            history=list(t.get('history',[]))
            if len(history)<2 or t.get('direction_suspicious',False):
                continue
            p0,p1=history[-2:]
            dt=float(p1[0])-float(p0[0])
            dx=float(p1[1])-float(p0[1])
            dy=float(p1[2])-float(p0[2])
            if (dt<=0 or dt>.35 or dy<max(12.,engine.min_approach_vy*dt)
                    or abs(dx)>max(12.,.25*dy)
                    or mapper.lane_for(float(p0[1]))!=lane_index
                    or mapper.lane_for(float(p1[1]))!=lane_index):
                continue
            speed=dy/dt
        if not math.isfinite(speed) or speed < engine.min_approach_vy:
            continue
        half=(float(t['h'])/2 + engine.crossing_half_height
              + max(18.0,float(chicken.get('h',60.0))*.31))
        distance=float(chicken['cy'])-float(t['cy'])
        age=max(0.0,now-float(t.get('ts',now)))
        # ROI resets remove tracks; a bounded detection gap may retain a trajectory.
        if distance < -half:
            continue
        if missing:
            # Missing foreground is not proof that a measured car departed.
            # Use the slowest positive measured estimate for its latest rear
            # exit, and the fastest for earliest front arrival. Only tracks
            # retained by MotionEngine's existing lifecycle reach this path.
            positive = [v for v in speeds if v >= engine.min_approach_vy]
            rear_exit = (distance+half)/min(positive)
            if age >= rear_exit:
                continue
        elif age > .35:
            continue
        # Use the earliest measured velocity estimate, including fit/net
        # trajectories which can lead the exponentially smoothed velocity.
        eta=max(0.0,(distance-half)/speed-age)
        arrivals.append((eta,int(t['id'])))
    return min(arrivals) if arrivals else (None,None)


def apply_guard(state, arrival, track_id, required):
    state.update(upstream_arrival_eta=arrival, upstream_threat_id=track_id,
                 upstream_required_seconds=float(required),
                 upstream_prediction_available=int(arrival is not None),
                 upstream_prediction_blocked=int(arrival is not None and arrival<=required))
    if state['upstream_prediction_blocked']:
        state['green_evidence_ok']=False
        state['green_evidence_reason']='UPSTREAM VEHICLE ARRIVAL'
    return state


def unresolved_vehicle(tracks, chicken, lane_x, engine, now, horizon):
    """Bounded uncertainty hold for recently observed, vehicle-sized objects.

    No velocity or probability is invented. Expiry uses the existing crossing
    horizon, and tracker reset/expiry also removes the evidence. A new measured
    trajectory is handled by predict_arrival instead.
    """
    if chicken is None:return None
    for t in tracks:
        if t.get('direction_valid') and not t.get('direction_suspicious'):
            continue
        if float(t.get('w',0)) < 2*engine.lane_visibility_half_width:
            continue
        if float(t.get('h',0)) < engine.crossing_half_height:
            continue
        if abs(float(t['cx'])-lane_x) > float(t['w'])/2+engine.lane_visibility_half_width:
            continue
        half=engine.crossing_half_height+max(18.,float(chicken.get('h',60.))*.31)
        if float(t['cy'])-float(t['h'])/2 > float(chicken['cy'])+half:
            continue # rear already observed beyond crossing
        age=max(0.,now-float(t.get('ts',now)))
        if age < horizon:
            return int(t['id'])
    return None


def apply_unresolved_guard(state, track_id, enforce=False):
    state['upstream_unresolved_vehicle']=track_id
    state['upstream_uncertainty_would_block']=int(track_id is not None)
    state['upstream_uncertainty_enforced']=bool(enforce)
    if track_id is not None and enforce:
        state['green_evidence_ok']=False
        state['green_evidence_reason']='UNRESOLVED INCOMING VEHICLE'
    return state
