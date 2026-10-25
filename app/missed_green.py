"""Rearm missed cues from newly observed traffic, not a cycle counter alone."""
class MissedGreenRearm:
    def __init__(self):
        self.key=None
        self.missed_at=None
        self.busy_cycle=None
        self.ready_cycle=None
        self.reason=''

    @staticmethod
    def target_key(state):
        return (int(state.get('target_lane_switches',0) or 0),
                int(state.get('viewport_rebase_count',0) or 0))

    def missed(self,signal,now):
        self.key=(int(signal.get('target_switches_at_signal',0) or 0),
                  int(signal.get('viewport_rebase_at_signal',0) or 0))
        self.missed_at=float(now)
        self.busy_cycle=None
        self.ready_cycle=None
        self.reason='MISSED GREEN: WAIT NEW VEHICLE'

    def allowed(self,state,now,cooldown):
        if self.missed_at is None:
            self.reason=''
            return True
        valid=bool(state.get('chicken_fresh',False)
            and state.get('target_lane_geometry_ok',False)
            and state.get('chicken_anchor_stable',False)
            and not state.get('tracking_rewarm',False)
            and state.get('scene_pan_stable',True))
        if self.target_key(state)!=self.key and valid:
            self.missed_at=None
            self.reason=''
            return True
        if not valid or not state.get('motion_corridor_available',False):
            self.busy_cycle=None
            self.ready_cycle=None
            self.reason='MISSED GREEN: WAIT FRESH TRACKING'
            return False
        cycle=state.get('dynamic_gap_cycle_id')
        if cycle is None:
            self.reason='MISSED GREEN: WAIT NEW VEHICLE'
            return False
        cycle=int(cycle)
        if not state.get('motion_corridor_clear',False):
            # The caller observes every analysis tick. Only occupancy seen AFTER
            # the miss is eligible; a counter that changed earlier cannot rearm.
            if float(now)>self.missed_at:
                self.busy_cycle=cycle
                self.ready_cycle=None
        elif self.busy_cycle is not None and cycle>self.busy_cycle:
            duration=float(state.get('motion_preceding_busy_duration') or 0.0)
            minimum=float(state.get('green_rearm_min_busy',.16))
            self.ready_cycle=cycle if duration>=minimum else None
            self.busy_cycle=None
        if float(now)-self.missed_at < float(cooldown):
            self.reason='MISSED GREEN: COOLDOWN'
            return False
        if self.ready_cycle!=cycle or not state.get('motion_corridor_clear',False):
            self.reason='MISSED GREEN: WAIT NEW VEHICLE'
            return False
        self.reason=''
        return True
