"""Expire presentation at its existing physical lease; never extend admission."""
import math


def deadline_for_state(state, decision_wall):
    # Only a verified gap has an explicitly measured action lease. Other
    # sources keep their existing V5 rules rather than inventing a new floor.
    if state.get('v5_gap_provenance') != 'verified-gap':
        return None
    value=state.get('v5_verified_gap_action_lease')
    try:
        lease=float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lease):
        return float(decision_wall)
    return float(decision_wall)+max(0.0,lease)


def expire_state(state, now):
    deadline=state.get('green_display_deadline')
    if (state.get('indicator_state') == 'CLEAR' and deadline is not None
            and float(now)>=float(deadline)):
        state=dict(state)
        state.update(indicator_state='ETA HOLD',green_confirmed=False,
                     green_evidence_ok=False, green_evidence_reason='ACTION LEASE EXPIRED',
                     clear_block_reason='ACTION LEASE EXPIRED',green_display_expired=1)
    return state


class DisplayLease:
    """A continuing offer can shrink its deadline, never roll it forward."""
    def __init__(self):
        self.key=None
        self.deadline=None

    def update(self,state,decision_wall):
        candidate=deadline_for_state(state,decision_wall)
        if candidate is None or not state.get('v5_decision',False):
            return None
        key=(state.get('lane'),state.get('target_lane_switches'),
             state.get('viewport_rebase_count'),state.get('dynamic_gap_cycle_id'))
        if key!=self.key:
            self.key=key
            self.deadline=candidate
        else:
            self.deadline=min(self.deadline,candidate)
        return self.deadline
