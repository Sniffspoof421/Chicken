"""Checkpoint traffic learning only while no jump permission is active."""
def idle_checkpoint_due(state,now,last,interval=90.):
    return bool(float(now)-float(last)>=max(30.,float(interval))
        and state.get('indicator_state') in ('WAIT','ETA HOLD','CHECKING')
        and not state.get('green_confirmed',False)
        and not state.get('green_evidence_ok',False)
        and not state.get('v5_decision',False)
        and not state.get('green_active',False)
        and not state.get('rearm_needed',False)
        and state.get('chicken_fresh',False)
        and state.get('chicken_anchor_stable',False)
        and state.get('processing_healthy',False)
        and not state.get('game_progress_scroll_context',False))
