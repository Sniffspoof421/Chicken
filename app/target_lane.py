class StableNextLane:
    """Stable IMMEDIATE next-lane target in screen coordinates.

    V4.4.0 assumed lane IDs/x positions progressed monotonically to the right.
    That is not true once the game viewport auto-scrolls. A stale target could
    remain 2-5 lane spacings ahead of the chicken while the actual next jump
    was only one spacing away.

    V4.4.1 locks by geometry, not by world/lane-ID monotonicity:
      * normal target should be roughly one lane spacing ahead,
      * a target > max_ahead_fraction spacings away is stale and is reacquired,
      * once the chicken reaches the target, the next proposed lane may have
        any local ID (IDs can repeat after scrolling),
      * lane-center drift is followed when the proposed immediate lane remains
        geometrically plausible.
    """

    def __init__(
        self,
        arrival_fraction=.22,
        switch_min_seconds=.35,
        min_ahead_fraction=.10,
        max_ahead_fraction=1.55,
        reanchor_fraction=.18,
        authoritative_min_fraction=.72,
        authoritative_max_fraction=1.28,
        sync_improvement_fraction=.14,
    ):
        self.arrival_fraction=float(arrival_fraction)
        self.switch_min_seconds=float(switch_min_seconds)
        self.min_ahead_fraction=float(min_ahead_fraction)
        self.max_ahead_fraction=float(max_ahead_fraction)
        self.reanchor_fraction=float(reanchor_fraction)
        # V5.3.3: a fresh chicken-relative proposal that is materially closer to
        # one full lane spacing is authoritative over a stale lock.  Previous
        # hysteresis only repaired targets that were too far ahead; consumed
        # targets sitting ~0.4-0.6 spacing ahead could survive for many seconds.
        self.authoritative_min_fraction=float(authoritative_min_fraction)
        self.authoritative_max_fraction=float(authoritative_max_fraction)
        self.sync_improvement_fraction=float(sync_improvement_fraction)

        self.lane_id=None
        self.lane_x=None
        self.set_at=0.0
        self.switches=0
        self.relocks=0
        self.last_reason='INIT'

    def rebase_viewport(self, dx):
        dx=float(dx or 0.0)
        if self.lane_x is not None:
            self.lane_x=float(self.lane_x)+dx
        if abs(dx) >= 1.0:
            self.last_reason='VIEW_REBASE'

    def force_reanchor(self, proposed, now, reason='SELF_HEAL'):
        """Force the target to the current geometric proposal.

        Used by the V5.1 tracking-health watchdog after the watched ROI has
        gone blind. Unlike reset(), this immediately establishes a usable
        target in the same coordinate frame so the motion ROI can rebuild
        without waiting for user viewport movement.
        """
        if not proposed:
            self.last_reason='SELF_HEAL_NO_PROPOSAL'
            return None
        pid, px = int(proposed[0][0]), float(proposed[0][1])
        changed = (
            self.lane_id is not None and (
                int(pid) != int(self.lane_id)
                or self.lane_x is None
                or abs(float(px)-float(self.lane_x)) > 1.0
            )
        )
        out = self._set(pid, px, float(now), str(reason), count_switch=changed)
        self.relocks += 1
        return out

    def reset(self):
        self.lane_id=None
        self.lane_x=None
        self.set_at=0.0
        self.last_reason='RESET'

    def _set(self, pid, px, now, reason, count_switch=True):
        changed = (
            self.lane_id is not None
            and (
                int(pid) != int(self.lane_id)
                or self.lane_x is None
                or abs(float(px)-float(self.lane_x)) > 1.0
            )
        )
        self.lane_id=int(pid)
        self.lane_x=float(px)
        self.set_at=float(now)
        self.last_reason=str(reason)
        if changed and count_switch:
            self.switches += 1
        if reason in ('STALE_GEOMETRY','VIEW_SCROLL','REANCHOR'):
            self.relocks += 1
        return (int(self.lane_id),float(self.lane_x))

    def forward_recovery_candidate(
        self, centers, chicken_x, spacing, min_ratio=.76, max_ratio=1.38,
        min_advance_fraction=.45,
    ):
        """Return a lane center suitable for recovering a consumed target.

        The normal lane proposal intentionally returns the nearest center ahead
        of the chicken. After a landing that nearest center can be the lane the
        chicken has already consumed, so asking the same proposal to repair the
        target creates a deadlock. This helper independently searches the road
        grid for a center roughly one spacing ahead and materially beyond the
        currently locked target.
        """
        if self.lane_x is None or not centers:
            return None
        cx=float(chicken_x)
        sp=max(40.0,float(spacing or 185.0))
        old_x=float(self.lane_x)
        lo=float(min_ratio); hi=float(max_ratio)
        min_advance=sp*float(min_advance_fraction)
        cand=[]
        for i,x in enumerate(centers):
            x=float(x)
            r=(x-cx)/sp
            if lo <= r <= hi and (x-old_x) >= min_advance:
                cand.append((abs(r-1.0), int(i), x, r))
        if not cand:
            return None
        cand.sort(key=lambda z:(z[0],z[2]))
        _,i,x,_=cand[0]
        return (int(i),float(x))

    def update(self, proposed, chicken_x, spacing, now):
        if not proposed:
            self.last_reason='NO_PROPOSAL'
            return None

        pid,px=int(proposed[0][0]),float(proposed[0][1])
        cx=float(chicken_x)
        spacing=max(40.0,float(spacing or 185.0))
        now=float(now)

        arrival_tol=max(28.0,spacing*self.arrival_fraction)
        min_ahead=max(12.0,spacing*self.min_ahead_fraction)
        max_ahead=spacing*self.max_ahead_fraction

        prop_dist=px-cx
        prop_valid=(min_ahead <= prop_dist <= max_ahead)

        if self.lane_id is None or self.lane_x is None:
            if not prop_valid:
                self.last_reason='BAD_INITIAL_PROPOSAL'
                return None
            return self._set(pid,px,now,'INITIAL',count_switch=False)

        old_x=float(self.lane_x)
        old_dist=old_x-cx
        age=max(0.0,now-float(self.set_at))

        # Critical V4.4.1 recovery: after viewport auto-scroll, the old target
        # can suddenly be 2-5 lane spacings ahead. Never keep such a target.
        old_stale=bool(
            old_dist > max_ahead
            or old_dist < -arrival_tol
        )
        if old_stale:
            if prop_valid:
                reason='VIEW_SCROLL' if old_dist > max_ahead else 'STALE_GEOMETRY'
                return self._set(pid,px,now,reason)
            self.last_reason='STALE_NO_VALID_PROPOSAL'
            return None

        # Same local lane ID but the road grid shifted materially on screen.
        # Follow the new center if it is still the immediate geometric lane.
        if pid == int(self.lane_id):
            if (
                prop_valid
                and abs(px-old_x) >= spacing*self.reanchor_fraction
            ):
                return self._set(pid,px,now,'REANCHOR',count_switch=False)
            self.last_reason='HOLD_SAME'
            return (int(self.lane_id),old_x)

        reached_old = old_dist <= arrival_tol

        # Preserve the normal completed-lane transition semantics.  If the
        # chicken has genuinely reached the old target, this is ARRIVED rather
        # than a geometry repair.  This branch intentionally precedes the
        # symmetric CHICKEN_SYNC repair below.
        if reached_old and prop_valid and age >= self.switch_min_seconds:
            return self._set(pid,px,now,'ARRIVED')

        # V5.3.3 symmetric chicken-sync.  The old code only preferred a new
        # proposal when the locked target was >1.20 spacings ahead.  Telemetry
        # also showed the opposite failure: a consumed target could remain
        # 0.25-0.60 spacings ahead while a current proposal sat near the true
        # one-spacing target.  In that case, re-anchor immediately once normal
        # switch hysteresis has elapsed.
        prop_ratio=prop_dist/spacing
        old_ratio=old_dist/spacing
        prop_authoritative=bool(
            self.authoritative_min_fraction <= prop_ratio
            <= self.authoritative_max_fraction
        )
        old_authoritative=bool(
            self.authoritative_min_fraction <= old_ratio
            <= self.authoritative_max_fraction
        )
        if prop_authoritative and age >= self.switch_min_seconds:
            old_err=abs(old_dist-spacing)
            prop_err=abs(prop_dist-spacing)
            if (
                not old_authoritative
                and prop_err + self.sync_improvement_fraction*spacing < old_err
            ):
                return self._set(pid,px,now,'CHICKEN_SYNC')

        # If both are plausible but the proposal is much closer to the expected
        # one-spacing geometry, prefer it. This catches silent auto-scrolls that
        # the global pan detector may miss.
        if prop_valid and age >= self.switch_min_seconds:
            old_err=abs(old_dist-spacing)
            prop_err=abs(prop_dist-spacing)
            if (
                old_dist > 1.20*spacing
                and prop_err + .18*spacing < old_err
            ):
                return self._set(pid,px,now,'VIEW_SCROLL')

        self.last_reason='HOLD_HYSTERESIS'
        return (int(self.lane_id),old_x)

    def geometry(self, chicken_x, spacing):
        if self.lane_x is None:
            return {
                'ok':False,'distance':None,'ratio':None,'reason':'NO_TARGET'
            }
        spacing=max(40.0,float(spacing or 185.0))
        d=float(self.lane_x)-float(chicken_x)
        r=d/spacing
        ok=bool(
            self.min_ahead_fraction <= r <= self.max_ahead_fraction
        )
        return {
            'ok':ok,'distance':float(d),'ratio':float(r),
            'reason':self.last_reason
        }
