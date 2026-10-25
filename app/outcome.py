from collections import deque
import time
import math
from .missed_green import MissedGreenRearm


class GreenJumpOutcomeTracker:
    """Validate GREEN using actual one-jump outcomes.

    State machine:
      READY -> GREEN SIGNAL -> ACTION -> PROVISIONAL LANDING
      -> grace period -> SUCCESS

    Any crash while ACTION or PROVISIONAL LANDING is active => FAILURE.

    A GREEN authorizes ONE jump only. If displacement grows beyond the expected
    one-jump envelope before a landing is confirmed, the attempt becomes
    CHAINED/UNVALIDATED and is never learned as a GREEN success.
    """

    def __init__(self, cfg):
        # While GREEN is still active, an action may begin at any time.
        # Once GREEN turns off, only this short human-reaction grace remains.
        self.action_window = float(cfg.get('action_window_seconds', 1.0))  # legacy
        self.post_green_action_grace = float(
            cfg.get('post_green_action_grace_seconds', 1.50)
        )
        # V4.4.10 display-only re-arm guard. This does not change prediction,
        # learning, ETA, or risk logic. It only prevents an ignored GREEN from
        # being immediately replaced by another GREEN from the next vehicle.
        self.unacted_green_rearm_seconds = float(
            cfg.get('unacted_green_rearm_seconds', 6.0)
        )
        # Once attribution grace expires, keep the old GREEN only as a
        # reaction-timing tombstone. It can teach end-to-end action latency,
        # but can never become a hazard success/failure label.
        self.late_observation_window = float(
            cfg.get('late_observation_window_seconds', 1.80)
        )
        self.strong_attribution_seconds = float(
            cfg.get('strong_attribution_seconds', .45)
        )
        self.action_start_dx = float(cfg.get('action_start_dx_px', 18))
        self.action_start_min_ratio = float(cfg.get('action_start_min_ratio', .24))
        self.expected_jump_px = float(cfg.get('expected_jump_px', 380))
        self.jump_min_ratio = float(cfg.get('jump_min_ratio', .68))
        self.jump_max_ratio = float(cfg.get('jump_max_ratio', 1.34))
        self.chain_ratio = float(cfg.get('chain_ratio', 1.55))
        self.success_hold = float(cfg.get('success_hold_seconds', .28))
        self.success_grace = float(cfg.get('success_grace_seconds', .70))
        self.landing_regression_px = float(cfg.get('landing_regression_px', 85))
        self.outcome_timeout = float(cfg.get('outcome_timeout_seconds', 3.0))
        self.stable_dx = float(cfg.get('stable_dx_px', 14))
        self.rearm_stable = float(cfg.get('rearm_stable_seconds', .45))
        self.rearm_geometry_stable = float(
            cfg.get('rearm_geometry_stable_seconds', .28)
        )
        self.stationary_dx = float(cfg.get('stationary_dx_px', 10))
        self.missing_attempt_timeout = float(cfg.get('missing_attempt_timeout_seconds', 1.25))
        self.progress_handoff_grace = float(
            cfg.get('progress_handoff_grace_seconds', 4.0)
        )
        self.progress_handoff_success_grace = float(
            cfg.get('progress_handoff_success_grace_seconds', .75)
        )

        self.current_signal = None
        self.pending_signal = None
        self.recent_expired_signal = None
        self.active_attempt = None
        self.provisional = None

        self.rearm_needed = False
        self.rearm_x = None
        self.rearm_since = None
        self.rearm_geometry_since = None
        self.rearm_geometry_key = None
        self.rearm_geometry_releases = 0

        self.last_x = None
        self.next_signal_id = 1
        self.step_history = deque(maxlen=30)

        self.green_signals = 0
        self.acted_signals = 0
        self.successes = 0
        self.failures = 0
        self.unacted = 0
        self.late_unattributed = 0
        self.chained = 0
        self.viewport_invalidated = 0
        self.viewport_rebases = 0
        # V5.3.8 diagnostics: old builds could fabricate a GREEN action from a
        # later crash. We now count and ignore those non-causal fallbacks.
        self.crash_fallback_ignored = 0
        self.multi_jump_unvalidated = 0
        # V5.4.0: count successful GREEN jumps closed by target-lane handoff.
        self.target_arrival_successes = 0
        self.progress_handoffs = 0
        self.missed_green_rearm=MissedGreenRearm()
        self.signal_diagnostics=[]
        self.last_unacted_green_end_ts = None
        self.last_unacted_cycle_id = None

    def rebase_viewport(self, dx):
        """Translate outcome coordinates with the game viewport.

        V5.2.6 cancelled GREEN attribution whenever the game/camera moved.
        That erased the exact acted GREEN we needed to learn from.  Rebase the
        screen-space coordinates instead; main.py separately prevents camera
        motion itself from being interpreted as a jump action.
        """
        dx=float(dx or 0.0)
        if abs(dx) < 1e-6:
            return 0
        self.viewport_rebases += 1
        coord_keys=(
            'baseline_x','action_start_x','last_x','max_x','landing_x','end_x'
        )
        for obj in (
            self.current_signal, self.pending_signal, self.recent_expired_signal,
            self.active_attempt, self.provisional
        ):
            if not isinstance(obj,dict):
                continue
            obj.pop('early_reset_candidate',None)
            obj.pop('early_downward_seen',None)
            for k in coord_keys:
                if obj.get(k) is not None:
                    obj[k]=float(obj[k])+dx
        if self.rearm_x is not None:
            self.rearm_x=float(self.rearm_x)+dx
        if self.last_x is not None:
            self.last_x=float(self.last_x)+dx
        return 1

    def invalidate_unacted_viewport(self, chicken=None, now=None):
        """Drop only unacted GREENs after a viewport change.

        An acted/provisional GREEN remains the owner of its jump outcome across
        camera motion, because its coordinates are rebased by rebase_viewport().
        Unacted safety permission is cancelled because the visual scene changed.
        """
        had=bool(
            self.current_signal is not None
            or self.pending_signal is not None
            or self.recent_expired_signal is not None
        )
        # Cancelling permission must not silently erase the audit trail.
        sig = self.current_signal or self.pending_signal or self.recent_expired_signal
        if sig is not None:
            event = dict(sig)
            event.update(kind='green_outcome', outcome='unknown',
                         unknown_reason='viewport_change_without_observed_action',
                         outcome_ts=float(time.time() if now is None else now),
                         one_jump_valid=False, training_eligible=False)
            self.signal_diagnostics.append(event)
        self.current_signal=None
        self.pending_signal=None
        self.recent_expired_signal=None
        if self.active_attempt is None and self.provisional is None:
            self.last_x=None if chicken is None else float(chicken.get('cx',0.0))
        if had:
            self.viewport_invalidated += 1
        return had

    def invalidate_viewport(self, chicken=None):
        """Cancel screen-coordinate outcome attribution after a viewport pan.

        This is NOT a success or a failure. Camera movement changes chicken X
        without changing game progress, so retaining the old baseline would
        create false GREEN failures.
        """
        had=bool(
            self.current_signal is not None
            or self.pending_signal is not None
            or self.active_attempt is not None
            or self.provisional is not None
        )
        src=self.active_attempt or self.provisional
        if src is not None and src.get('input_owned'):
            self.signal_diagnostics.append(dict(src,kind='green_outcome',outcome='unknown',
                outcome_ts=time.time(),unknown_reason='input_attempt_viewport_invalidated',
                one_jump_valid=False,training_eligible=False))
        self.current_signal=None
        self.pending_signal=None
        self.recent_expired_signal=None
        self.active_attempt=None
        self.provisional=None
        self.rearm_needed=False
        self.rearm_x=None
        self.rearm_since=None
        self.last_x=None if chicken is None else float(chicken.get('cx',0.0))
        if had:
            self.viewport_invalidated += 1
        return had

    def expected_step(self):
        if len(self.step_history) >= 3:
            a = sorted(self.step_history)
            return float(a[len(a)//2])
        return self.expected_jump_px

    def _snapshot(self, state, chicken, now):
        l1 = state.get('lane1') or {}
        pat = l1.get('pattern') or {}
        tpat = l1.get('type_pattern') or {}
        return {
            'signal_id': self.next_signal_id,
            'start_ts': float(now),
            'end_ts': float(now),
            'duration': 0.0,
            'baseline_x': None if chicken is None else float(chicken.get('cx', 0.0)),
            'baseline_y': None if chicken is None else chicken.get('cy'),
            'lane': state.get('lane', ''),
            'eta_source': state.get('eta_source', 'unknown'),
            'eta': state.get('effective_eta'),
            'raw_risk': state.get('raw_risk', state.get('risk')),
            'display_risk': state.get('display_risk'),
            'features': None if state.get('training_features') is None else list(state.get('training_features')),
            'speed_pattern': pat.get('sequence', '-'),
            'type_pattern': tpat.get('sequence', '-'),
            'pattern_support': pat.get('support', 0),
            'pattern_confidence': pat.get('confidence', 0.0),
            'expected_gap': pat.get('expected_gap'),
            'p25_gap': pat.get('p25_gap'),
            'p_next_slow': pat.get('p_next_slow', 0.0),
            'p_next_medium': pat.get('p_next_medium', 0.0),
            'p_next_fast': pat.get('p_next_fast', 0.0),
            'czn_calibrated': bool(state.get('czn_calibrated', False)),
            'czn_confirmed_events': int(state.get('czn_confirmed_events', 0)),
            'czn_required_events': int(state.get('czn_required_events', 0)),
            'czn_unique_raw_tracks': int(state.get('czn_unique_raw_tracks', 0)),
            'czn_required_unique_tracks': int(state.get('czn_required_unique_tracks', 0)),
            'czn_calibration_mode': state.get('czn_calibration_mode', 'WAIT'),
            'czn_speed_reference': state.get('czn_speed_reference'),
            'adaptive_confidence': state.get('adaptive_confidence'),
            'adaptive_required_confidence': state.get('adaptive_required_confidence'),
            'regime_id': state.get('regime_id'),
            'regime_samples': state.get('regime_samples'),
            'safety_context': {
                'lane': int(state.get('lane', -1)) if str(state.get('lane','-1')).lstrip('-').isdigit() else -1,
                'source': str(state.get('eta_source','unknown')),
                'eta': float(state.get('effective_eta') or 0.0),
                'raw_risk': float(state.get('raw_risk', state.get('risk',50)) or 0.0),
                'motion_ratio': float(state.get('motion_corridor_ratio',1.0) or 0.0),
                'motion_dwell': float(state.get('motion_clear_dwell',0.0) or 0.0),
                'clear_dwell': float(state.get('clear_dwell',0.0) or 0.0),
                'czn_speed': float(state.get('czn_speed_reference',0.0) or 0.0),
                'adaptive_conf': float(state.get('adaptive_confidence',0.0) or 0.0),
                'gap25': float(state.get('regime_gap_p25',1.25) or 0.0),
                'fast_frac': float(state.get('regime_fast_fraction',.33) or 0.0),
                'pattern_p25': float(state.get('current_pattern_p25') or 0.0),
                'pattern_fast': float(state.get('current_pattern_p_next_fast',1.0) or 0.0),
                'uncertain': float(state.get('uncertain_incoming_count',0) or 0.0),
                'stage_score': float(state.get('stage_difficulty_score',0.0) or 0.0),
            },
            # V5.2.9: use the actual locked target geometry first. V5.2.8
            # inherited a clipped next_lane_distance and therefore expected a
            # ~320 px jump in a layout where one lane is commonly 400-480 px.
            'expected_jump_px': float(
                state.get('target_lane_distance')
                if state.get('target_lane_distance') not in (None,'')
                else state.get('next_lane_distance')
                if state.get('next_lane_distance') is not None
                else self.expected_step()
            ),
            # Exact V5 decision state. V5.2.1 logged GREEN failures but the
            # SafeWindowPredictor could not train the state that actually
            # produced the signal. Carry it through action/outcome attribution.
            'v5_feature_vector': (
                None if state.get('v5_feature_vector') is None
                else list(state.get('v5_feature_vector'))
            ),
            'v5_safe_probability': state.get('v5_safe_probability'),
            'v5_safe_threshold': state.get('v5_safe_threshold'),
            'v5_failure_similarity': state.get('v5_failure_similarity',0.0),
            'v5_cycle_id': state.get('dynamic_gap_cycle_id'),
            'v5_gap_provenance': state.get('v5_gap_provenance','unknown'),
            'timing_source': (
                'dynamic-gap'
                if str(state.get('v5_gap_provenance','')) in ('verified-gap','slow-before')
                else 'clear-zone'
                if str(state.get('v5_gap_provenance','')) == 'observed-clear'
                else str(state.get('eta_source_for_gate',state.get('eta_source','unknown')))
            ),
            'green_required_eta': state.get('green_required_eta'),
            # V5.4.0: preserve target ownership at GREEN time. If the lane-lock
            # later reports ARRIVED and advances exactly once, that is stronger
            # landing evidence than waiting for several extra fresh CV frames.
            'target_lane_x_at_signal': state.get('target_lane_x'),
            'target_switches_at_signal': int(state.get('target_lane_switches',0) or 0),
            'viewport_rebase_at_signal': int(state.get('viewport_rebase_count',0) or 0),
            'v5_historical_slow_after_risk': state.get('v5_historical_slow_after_risk',0.0),
        }

    def _moving(self, chicken):
        if chicken is None:
            return False
        x = float(chicken.get('cx', 0.0))
        if self.last_x is None:
            self.last_x = x
            return False
        moving = abs(x - self.last_x) > self.stationary_dx
        self.last_x = x
        return moving

    def _note_missed_green(self,signal,now):
        self.missed_green_rearm.missed(signal,now)
        self.signal_diagnostics.append(dict(kind='green_unacted',
            signal_id=signal.get('signal_id'),event_ts=float(now),
            start_ts=signal.get('start_ts'),end_ts=signal.get('end_ts'),
            target_switches_at_signal=signal.get('target_switches_at_signal'),
            v5_cycle_id=signal.get('v5_cycle_id')))

    def _expire_signal(self, now):
        if self.pending_signal is not None:
            age = now - float(self.pending_signal['end_ts'])
            if age > self.post_green_action_grace:
                self.unacted += 1
                self.recent_expired_signal = dict(self.pending_signal)
                self.recent_expired_signal['timing_only_expired_ts'] = float(now)
                # With the longer causal-action grace, start same-cycle
                # presentation cooldown when we finally classify the signal
                # unacted, not at its much earlier display end.
                self.last_unacted_green_end_ts = float(now)
                self.last_unacted_cycle_id = self.pending_signal.get('v5_cycle_id')
                self._note_missed_green(self.pending_signal,now)
                self.pending_signal = None

        # Timing-only tombstone eventually expires too.
        if self.recent_expired_signal is not None:
            age = now - float(
                self.recent_expired_signal.get(
                    'end_ts',
                    self.recent_expired_signal.get('timing_only_expired_ts',now)
                )
            )
            if age > self.late_observation_window:
                self.recent_expired_signal = None

    def green_display_allowed(self, now, cycle_id=None, state=None):
        """Return whether a *new* GREEN may be displayed.

        Existing CLEAR is allowed to continue. Prediction/learning is untouched;
        this is only a presentation/admission guard for repeated unacted signals.
        """
        now = float(now)
        # Observe fresh traffic even while an older action/signal is resolving.
        rearm_ok=(True if state is None else self.missed_green_rearm.allowed(
            state,now,self.unacted_green_rearm_seconds))
        if self.current_signal is not None:
            return True
        if (
            self.pending_signal is not None
            or self.active_attempt is not None
            or self.provisional is not None
            or self.rearm_needed
        ):
            return False
        if not rearm_ok:
            return False
        if state is not None:
            return True
        if self.last_unacted_green_end_ts is not None:
            if now - float(self.last_unacted_green_end_ts) < self.unacted_green_rearm_seconds:
                # V5.4.2: suppress repeated flicker from the SAME physical gap,
                # not a genuinely new busy->clear cycle. V5.4.1's blanket 6 s
                # blackout hid valid opportunities after short unacted GREENs.
                try:
                    if (state is None and cycle_id is not None and self.last_unacted_cycle_id is not None
                            and int(cycle_id) != int(self.last_unacted_cycle_id)):
                        return True
                except Exception:
                    pass
                return False
        return True

    def _action_start_threshold(self, sig):
        """Lane-scaled movement needed before GREEN owns a jump.

        V5.4.1 used an 18 px absolute threshold. In real telemetry the chicken
        detector can wander 50-70 px while standing still. V5.4.6 therefore
        requires about one quarter of a lane before GREEN owns a jump. The longer
        causal grace below compensates for the later confirmation point.
        """
        try:
            step=max(80.0,float(sig.get('expected_jump_px',self.expected_step())))
        except Exception:
            step=max(80.0,float(self.expected_step()))
        return float(max(self.action_start_dx,self.action_start_min_ratio*step))

    def _start_action_if_needed(self, chicken, now, state=None):
        if chicken is None or self.active_attempt is not None or self.provisional is not None:
            return None
        # V5.4.7: generic TRACK/MOTION REWARM can be caused by the jump itself.
        # Block only a real coordinate-frame movement/reframe or stale chicken.
        if state is not None and (
            bool(state.get('scene_pan_active',False))
            or bool(state.get('game_progress_scroll_active',False))
            or bool(state.get('game_progress_scroll_settling',False))
            or bool(state.get('fullscreen_reframe_active',False))
            or not bool(state.get('chicken_fresh',True))
        ):
            return None

        # Active GREEN has no post-signal age limit. A signal that already
        # disappeared is attributable only inside a short reaction grace.
        sig = self.current_signal if self.current_signal is not None else self.pending_signal
        timing_only = False
        if sig is None and self.recent_expired_signal is not None:
            sig = self.recent_expired_signal
            timing_only = True

        if sig is None or sig.get('baseline_x') is None:
            return None

        is_pending = (
            self.current_signal is None
            and not timing_only
        )
        if timing_only:
            post_delay = now - float(sig['end_ts'])
            if post_delay > self.late_observation_window:
                self.recent_expired_signal = None
                return None
            x = float(chicken.get('cx', sig['baseline_x']))
            dx = x - float(sig['baseline_x'])
            if dx < self._action_start_threshold(sig):
                return None

            self.late_unattributed += 1
            self.recent_expired_signal = None
            return {
                'kind': 'late_unattributed_action',
                'signal_id': sig['signal_id'],
                'eta_source': sig.get('eta_source','unknown'),
                'lane': sig.get('lane'),
                'eta': sig.get('eta'),
                'green_start_ts': float(sig.get('start_ts',sig['end_ts'])),
                'signal_end_ts': float(sig['end_ts']),
                'action_seen_ts': float(now),
                'action_delay_from_start': float(
                    now - float(sig.get('start_ts',sig['end_ts']))
                ),
                'post_green_delay': float(post_delay),
                'signal_duration': float(sig.get('duration',0.0)),
                'forward_dx': float(dx),
                'timing_only': True,
            }

        if is_pending:
            signal_age = now - float(sig['end_ts'])
            if signal_age > self.post_green_action_grace:
                # If motion is already visible after the grace, remember that
                # this was a late/unattributed action. Do NOT turn it into a
                # safe/unsafe supervised label.
                x = float(chicken.get('cx', sig['baseline_x']))
                dx = x - float(sig['baseline_x'])
                if dx >= self._action_start_threshold(sig):
                    self.late_unattributed += 1
                    self.pending_signal = None
                    return {
                        'kind': 'late_unattributed_action',
                        'signal_id': sig['signal_id'],
                        'eta_source': sig.get('eta_source','unknown'),
                        'lane': sig.get('lane'),
                        'green_start_ts': float(sig.get('start_ts',sig['end_ts'])),
                        'signal_end_ts': float(sig['end_ts']),
                        'action_seen_ts': float(now),
                        'action_delay_from_start': float(
                            now - float(sig.get('start_ts',sig['end_ts']))
                        ),
                        'post_green_delay': float(signal_age),
                        'signal_duration': float(sig.get('duration',0.0)),
                        'forward_dx': float(dx),
                        'timing_only': True,
                    }

                self.unacted += 1
                self.recent_expired_signal = dict(sig)
                self.recent_expired_signal[
                    'timing_only_expired_ts'
                ] = float(now)
                self.last_unacted_green_end_ts = float(now)
                self.last_unacted_cycle_id = sig.get('v5_cycle_id')
                self._note_missed_green(sig,now)
                self.pending_signal = None
                return None

        x = float(chicken.get('cx', sig['baseline_x']))
        dx = x - float(sig['baseline_x'])
        if dx < self._action_start_threshold(sig):
            return None

        self.acted_signals += 1
        a = dict(sig)
        a.update({
            'action_start_ts': float(now),
            'action_start_x': x,
            'last_x': x,
            'max_x': x,
            'stable_since': None,
            'expected_jump_px': float(sig.get('expected_jump_px', self.expected_step())),
            'post_green_delay': (
                max(0.0, float(now) - float(sig['end_ts']))
                if is_pending else 0.0
            ),
            'attribution': 'post_green_grace' if is_pending else 'green_active',
            'attribution_confidence': (
                1.0 if not is_pending
                else 1.0 if signal_age <= self.strong_attribution_seconds
                else max(.45, 1.0 - .40 * (
                    (signal_age-self.strong_attribution_seconds) /
                    max(.05, self.post_green_action_grace-self.strong_attribution_seconds)
                ))
            ),
        })
        self.active_attempt = a
        self.current_signal = None
        self.pending_signal = None
        self.rearm_needed = True
        self.rearm_x = None
        self.rearm_since = None
        return {
            'kind': 'action_started',
            'signal_id': a['signal_id'],
            'post_green_delay': a['post_green_delay'],
            'attribution': a['attribution'],
            'attribution_confidence': a.get('attribution_confidence',1.0),
        }


    def observe_input(self, record, now):
        """Arm one cue from a valid Space edge; movement still validates input.

        Mouse/UI presses and other controls are diagnostic only. A second
        Space cancels attribution rather than blaming a later jump on this cue.
        """
        if record.get('control') != 'space':
            return None
        if self.active_attempt is not None or self.provisional is not None:
            src=self.active_attempt or self.provisional
            if src.get('input_owned') and float(record['timestamp']) > src['action_start_ts']:
                event=dict(src,kind='green_outcome',outcome='unknown',outcome_ts=now,
                           unknown_reason='additional_input_before_resolution',one_jump_valid=False)
                self.active_attempt=None;self.provisional=None
                self.signal_diagnostics.append(event)
            return None
        sig=self.current_signal or self.pending_signal
        # Explicit off-GREEN input outranks a later CV movement guess. Do not
        # allow post-GREEN grace to relabel this same manual/late action.
        if (sig is not None and not record.get('cue_within_deadline')
                and record.get('foreground')
                and record.get('foreground') == record.get('cue_foreground')
                and 0 <= now-float(record['timestamp']) <= .75
                and float(record['timestamp']) >= float(sig['start_ts'])):
            self.signal_diagnostics.append(dict(sig,kind='green_outcome',
                outcome='unknown',outcome_ts=float(now),
                unknown_reason='recorded_input_outside_green',
                training_eligible=False,one_jump_valid=False,
                recorded_input_ts=float(record['timestamp'])))
            self.current_signal=None;self.pending_signal=None;self.recent_expired_signal=None
            self.rearm_needed=True;self.rearm_x=None;self.rearm_since=None
            return None
        if (sig is None or not record.get('cue_within_deadline')
                or record.get('signal_id') != sig.get('signal_id')
                or record.get('target_lane_switches') != sig.get('target_switches_at_signal')
                or not record.get('foreground')
                or record.get('foreground') != record.get('cue_foreground')
                or not 0 <= now-float(record['timestamp']) <= .75
                or float(record['timestamp']) < float(sig['start_ts'])):
            return None
        deadline=record.get('green_display_deadline')
        if deadline is None or float(record['timestamp']) >= float(deadline):
            return None
        step=float(sig.get('expected_jump_px',self.expected_step()))
        if abs(float(record.get('chicken_x') or 0)-float(sig['baseline_x'])) > .1*step:
            return None
        a=dict(sig)
        x=float(sig['baseline_x'])
        a.update(action_start_ts=float(record['timestamp']),action_start_x=x,
                 last_x=x,max_x=x,stable_since=None,expected_jump_px=step,
                 post_green_delay=0.,attribution='recorded_space_input',
                 attribution_confidence=1.,input_owned=True,input_movement_seen=False,
                 input_validated_deadline=float(deadline),
                 weak_action_attribution=True)
        self.active_attempt=a
        self.current_signal=None;self.pending_signal=None;self.recent_expired_signal=None
        self.acted_signals+=1;self.rearm_needed=True;self.rearm_x=None;self.rearm_since=None
        event=dict(kind='action_started',signal_id=a['signal_id'],
                   event_ts=a['action_start_ts'],attribution='recorded_space_input')
        self.signal_diagnostics.append(event)
        return event

    def confirm_input_movement(self, chicken):
        a=self.active_attempt
        if (a is None or not a.get('input_owned') or chicken is None
                or not chicken.get('detected',False)):
            return
        dx=float(chicken['cx'])-float(a['baseline_x'])
        dy=abs(float(chicken['cy'])-float(a.get('baseline_y',chicken['cy'])))
        step=max(80.,float(a['expected_jump_px']))
        a['max_x']=max(float(a.get('max_x',a['baseline_x'])),float(chicken['cx']))
        # Independent input plus early displacement is sufficient; without an
        # input the existing 24%-of-lane action threshold is unchanged.
        if self.action_start_dx <= dx <= self.chain_ratio*step or (abs(dx)<.24*step and dy>=.06*step):
            a['input_movement_seen']=True
            a['weak_action_attribution']=False
        # Downward motion before substantial forward travel is diagnostic of
        # an aborted jump, but alone is never a failure label.
        if (float(chicken['cy'])-float(a.get('baseline_y',chicken['cy'])) >= .06*step
                and 0 <= dx < .35*step):
            a['early_downward_seen']=True

    def _early_input_reset(self, state, chicken, now):
        """Resolve a bounded early-fall + stable backward-reset sequence.

        Requires real input, fresh movement, downward evidence before a landing,
        no viewport transition, no large forward progress, and two stable reset
        observations. A disappearance or coordinate change alone cannot train.
        """
        a=self.active_attempt
        if a is None or not a.get('input_owned'):
            return None
        if ((state.get('scene_pan_active',False) and not state.get('raw_scene_pan_ignored',False))
                or any(state.get(k,False) for k in (
            'game_progress_scroll_active',
            'game_progress_scroll_settling','fullscreen_reframe_active'))):
            a.pop('early_reset_candidate',None)
            a.pop('early_downward_seen',None)
            return None
        if chicken is None or not chicken.get('detected',True):
            a.pop('early_reset_candidate',None)
            return None
        step=max(80.,float(a['expected_jump_px']))
        x=float(chicken['cx']);y=float(chicken.get('cy',a.get('baseline_y',0.)))
        baseline=float(a['baseline_x'])
        age=float(now)-float(a['action_start_ts'])
        qualifies=(
            a.get('input_movement_seen') and a.get('early_downward_seen')
            and 0 <= age <= self.outcome_timeout
            and float(a.get('max_x',baseline))-baseline < .35*step
            and .65*step <= baseline-x <= 1.35*step
            and abs(y-float(a.get('baseline_y',y))) <= .04*step
        )
        if not qualifies:
            a.pop('early_reset_candidate',None)
            return None
        c=a.get('early_reset_candidate')
        if c is None or abs(x-c['x'])>self.stable_dx:
            a['early_reset_candidate']=dict(ts=float(now),x=x)
            return None
        if float(now)-c['ts'] < self.success_hold:
            return None
        event=self.on_crash(dict(event_time=c['ts'],
            reason='input_owned_early_fall_reset',reset_x=x),now)
        if event is not None:
            event['failure_type']='early_fall_stable_reset'
        return event

    def expire_display(self, now):
        """Close the shown GREEN at its deadline, even between analysis ticks."""
        if self.current_signal is None:
            return
        sig=self.current_signal
        sig['end_ts']=max(float(sig['start_ts']),float(now))
        sig['duration']=sig['end_ts']-float(sig['start_ts'])
        self.pending_signal=sig
        self.current_signal=None

    def _progress_handoff_if_needed(self, state, chicken, now):
        """Recover GREEN ownership when low FPS hides the forward animation.

        This requires positive game-progress evidence, never crash geometry:
        target ownership advances exactly once, the target lock reports a real
        VIEW_SCROLL/progress state, and a fresh chicken reappears roughly one
        lane left of the GREEN baseline inside a bounded grace.
        """
        if (
            state is None or chicken is None
            or state.get('reset_candidate_pending',False)
            or state.get('reset_confirmed_this_tick',False)
            or self.active_attempt is not None
            or self.provisional is not None
        ):
            return None

        sig=(self.current_signal or self.pending_signal or self.recent_expired_signal)
        if sig is None or sig.get('baseline_x') is None:
            return None

        try:
            end_ts=float(sig.get('end_ts',sig.get('start_ts',now)))
            if float(now)-end_ts > self.progress_handoff_grace:
                return None
            start_sw=int(sig.get('target_switches_at_signal',0) or 0)
            cur_sw=int(state.get('target_lane_switches',0) or 0)
            if cur_sw != start_sw+1:
                return None
            reason=str(state.get('target_lane_lock_reason','') or '')
            explicit_progress=bool(
                reason == 'VIEW_SCROLL'
                or state.get('game_progress_scroll_active',False)
                or state.get('fullscreen_reframe_active',False)
            )
            if not explicit_progress:
                return None
            if not bool(state.get('chicken_fresh',True)):
                return None

            baseline=float(sig['baseline_x'])
            x=float(chicken.get('cx',baseline))
            step=max(80.0,float(sig.get('expected_jump_px',self.expected_step())))
            if x > baseline-.45*step:
                return None
        except Exception:
            return None

        p=dict(sig)
        p.update({
            'kind':'provisional_landing',
            'action_start_ts':float(now),
            'action_start_x':float(x),
            'post_green_delay':max(0.0,float(now)-float(sig.get('end_ts',now))),
            'attribution':'progress_handoff',
            'attribution_confidence':.92,
            'synthetic_progress_handoff':True,
            'landing_ts':float(now),
            'landing_x':float(x),
            'progress_landing_x':float(x),
            'progress_target_switch':int(cur_sw),
            'progress_success_grace':float(self.progress_handoff_success_grace),
            'forward_dx':float(step),
            'max_forward_dx':float(step),
            'one_jump_valid':True,
            'landing_source':'progress_scroll_handoff',
        })
        self.acted_signals += 1
        self.progress_handoffs += 1
        self.provisional=p
        self.current_signal=None
        self.pending_signal=None
        self.recent_expired_signal=None
        self.rearm_needed=True
        self.rearm_x=float(x)
        self.rearm_since=float(now)
        return {
            'kind':'action_started',
            'signal_id':p['signal_id'],
            'post_green_delay':p['post_green_delay'],
            'attribution':'progress_handoff',
            'attribution_confidence':.92,
        }

    def _expire_missing_attempt(self, chicken, now):
        """Release a GREEN attempt if CV disappears for too long.

        This is UNKNOWN, never failure/success training. It exists solely to
        prevent the UI/next-lane analysis from remaining JUMPING for several
        seconds when the chicken detector drops out after a move.
        """
        if self.active_attempt is None:
            return None
        a=self.active_attempt
        fresh = chicken is not None and chicken.get('detected', True)
        if fresh:
            a.pop('missing_since', None)
            return None
        # Measure continuous absence, not elapsed time since the input.
        missing_since = a.setdefault('missing_since', float(now))
        absent_for = float(now) - missing_since
        attempt_age = float(now) - float(a.get('action_start_ts', now))
        if absent_for < self.missing_attempt_timeout and attempt_age < self.outcome_timeout:
            return None
        event=dict(a)
        event.update({
            'kind':'green_outcome',
            'outcome':'unknown',
            'outcome_ts':float(now),
            'end_x':a.get('last_x',a.get('max_x',a.get('baseline_x'))),
            'forward_dx':(
                float(a.get('max_x',a.get('baseline_x',0.0)))
                - float(a.get('baseline_x',0.0))
            ),
            'unknown_reason':'chicken_detection_timeout',
        })
        self.active_attempt=None
        self.provisional=None
        self.rearm_needed=True
        self.rearm_x=None
        self.rearm_since=None
        return event

    def _settled_landing(self, attempt, chicken, now):
        """Require fresh, continuous ground-height observations before finality.

        A target switch can happen during the jump/death animation. It is not
        itself evidence that the chicken survived landing.
        """
        if chicken is None or not chicken.get('detected', True):
            attempt.pop('ground_landing', None)
            return False
        x = float(chicken['cx'])
        y = chicken.get('cy')
        baseline_y = attempt.get('baseline_y')
        step = max(80., float(attempt.get('expected_jump_px', self.expected_step())))
        if (y is None or baseline_y is None
                or not all(math.isfinite(float(v)) for v in (x,y,baseline_y))
                or abs(float(y)-float(baseline_y)) > .04*step):
            attempt.pop('ground_landing', None)
            return False
        prior = attempt.get('ground_landing')
        if prior is None or abs(x-prior['x']) > self.stable_dx:
            attempt['ground_landing'] = {'since': float(now), 'x': x, 'n': 1}
            return False
        prior['n'] += 1
        return prior['n'] >= 2 and float(now)-prior['since'] >= self.success_hold

    def _target_arrival_success(self, state, chicken, now):
        """Finalize an owned one-lane landing before later viewport/reset events."""
        a=self.active_attempt if self.active_attempt is not None else self.provisional
        if a is None or state is None:
            return None
        if chicken is None or not state.get('chicken_fresh',True) or not chicken.get('detected',True):
            a.pop('ground_landing', None)
            return None
        try:
            start_sw=int(a.get('target_switches_at_signal',0) or 0)
            cur_sw=int(state.get('target_lane_switches',0) or 0)
            if cur_sw != start_sw + 1:
                return None
            if int(state.get('viewport_rebase_count',0) or 0) != int(
                a.get('viewport_rebase_at_signal',state.get('viewport_rebase_count',0)) or 0
            ):
                return None
            baseline=float(a.get('baseline_x',0.0))
            x=float(chicken.get('cx',baseline))
            step=max(80.0,float(a.get('expected_jump_px',self.expected_step())))
            disp=x-baseline
            old_target=a.get('target_lane_x_at_signal')
            if old_target is not None:
                target_error=abs(x-float(old_target))
                if target_error > .34*step:
                    return None
            if not (.65*step <= disp <= 1.38*step):
                return None
        except Exception:
            return None

        if not self._settled_landing(a, chicken, now):
            return None

        # Keep outcome='success' for existing learners/CSV readers; the explicit
        # terminal state records stronger evidence without changing their API.
        event=dict(a)
        event.update(kind='green_outcome', outcome='success',
                     outcome_state='SUCCESS_FINAL', outcome_ts=float(now),
                     landing_ts=float(now), end_x=x, landing_x=x,
                     forward_dx=disp, one_jump_valid=True,
                     landing_source='target_switch_advance')
        self.successes += 1
        self.target_arrival_successes += 1
        self.step_history.append(float(disp))
        self.active_attempt=None
        self.provisional=None
        self.rearm_needed=True
        self.rearm_x=x
        self.rearm_since=float(now)
        return event

    def _attempt_progress(self, chicken, now):
        a = self.active_attempt
        if a is None or chicken is None:
            return []

        x = float(chicken.get('cx', a['last_x']))
        previous_max_x = float(a['max_x'])
        a['max_x'] = max(previous_max_x, x)
        step = max(80.0, float(a['expected_jump_px']))
        disp = x - float(a['baseline_x'])

        # V5.3.8: enforce ONE-JUMP ownership before regression/failure logic.
        # A later reset after >1.55 lane progress belongs to a chained/manual
        # continuation, not to the GREEN that authorized the first jump.
        max_disp = float(a['max_x']) - float(a['baseline_x'])
        if max_disp > self.chain_ratio * step:
            event = dict(a)
            event.update({
                'kind': 'green_outcome',
                'outcome': 'chained_unvalidated',
                'outcome_ts': float(now),
                'end_x': x,
                'forward_dx': max_disp,
                'one_jump_valid': False,
            })
            self.chained += 1
            self.multi_jump_unvalidated += 1
            self.active_attempt = None
            self.rearm_needed = True
            self.rearm_x = x
            self.rearm_since = None
            return [event]

        # Only a regression that happened inside the one-jump envelope can be
        # blamed on this GREEN.
        if (
            max_disp >= self.jump_min_ratio * step
            and float(a['max_x']) - x >= self.landing_regression_px
        ):
            event = dict(a)
            event.update({
                'kind': 'green_outcome',
                'outcome': 'failure',
                'outcome_ts': float(now),
                'end_x': x,
                'forward_dx': disp,
                'max_forward_dx': max_disp,
                'crash_reason': 'jump_regression_reset',
                'one_jump_valid': True,
            })
            self.failures += 1
            self.active_attempt = None
            self.rearm_needed = True
            self.rearm_x = x
            self.rearm_since = None
            return [event]

        lo = self.jump_min_ratio * step
        hi = self.jump_max_ratio * step

        if lo <= disp <= hi:
            if abs(x - float(a['last_x'])) <= self.stable_dx:
                if a.get('stable_since') is None:
                    a['stable_since'] = float(now)
                elif now - float(a['stable_since']) >= self.success_hold:
                    p = dict(a)
                    p.update({
                        'kind': 'provisional_landing',
                        'landing_ts': float(now),
                        'landing_x': x,
                        'forward_dx': disp,
                    })
                    self.provisional = p
                    self.active_attempt = None
                    self.rearm_x = x
                    self.rearm_since = float(now)
                    return [{'kind': 'provisional_landing', 'signal_id': p['signal_id']}]
            else:
                a['stable_since'] = None
        else:
            a['stable_since'] = None

        a['last_x'] = x

        if now - float(a['action_start_ts']) > self.outcome_timeout:
            event = dict(a)
            event.update({
                'kind': 'green_outcome',
                'outcome': 'unknown',
                'outcome_ts': float(now),
                'end_x': x,
                'forward_dx': disp,
            })
            self.active_attempt = None
            self.rearm_needed = True
            self.rearm_x = x
            self.rearm_since = None
            return [event]

        return []

    def _provisional_progress(self, chicken, now):
        p = self.provisional
        if p is None:
            return []

        if chicken is None:
            p.pop('ground_landing', None)
            # Let CrashDetector resolve a disappearance/reset. Do not grant
            # success while the target is not visible.
            return []

        if str(p.get('landing_source','')) == 'progress_scroll_handoff':
            x=float(chicken.get('cx',p.get('progress_landing_x',0.0)))
            landing_x=float(p.get('progress_landing_x',x))
            step=max(80.0,float(p.get('expected_jump_px',self.expected_step())))
            if abs(x-landing_x) > .28*step:
                return []
            if now-float(p.get('landing_ts',now)) >= float(
                p.get('progress_success_grace',self.progress_handoff_success_grace)
            ):
                event=dict(p)
                event.update({
                    'kind':'green_outcome',
                    'outcome':'unknown',
                    'unknown_reason':'scroll_without_independent_landing_evidence',
                    'training_eligible':False,
                    'outcome_ts':float(now),
                    'end_x':float(x),
                    'forward_dx':float(step),
                    'max_forward_dx':float(step),
                    'one_jump_valid':True,
                })
                # Coordinate-only scroll is ambiguous: never feed a SAFE label.
                self.provisional=None
                self.rearm_needed=True
                self.rearm_x=float(x)
                self.rearm_since=float(now)
                return [event]
            return []

        x = float(chicken.get('cx', p.get('landing_x', 0.0)))
        step = max(80.0, float(p.get('expected_jump_px', self.expected_step())))
        disp = x - float(p['baseline_x'])
        landing_x = float(p.get('landing_x', x))

        # V5.3.8: if progress has already escaped the one-jump envelope, the
        # original GREEN no longer owns any later reset/crash.
        max_disp = max(
            float(p.get('max_x', landing_x)) - float(p['baseline_x']),
            disp,
        )
        if max_disp > self.chain_ratio * step:
            event = dict(p)
            event.update({
                'kind': 'green_outcome',
                'outcome': 'chained_unvalidated',
                'outcome_ts': float(now),
                'end_x': x,
                'forward_dx': max_disp,
                'one_jump_valid': False,
            })
            self.chained += 1
            self.multi_jump_unvalidated += 1
            self.provisional = None
            self.rearm_needed = True
            self.rearm_x = x
            self.rearm_since = None
            return [event]

        # A regression inside the one-jump envelope remains a real failure.
        if (
            landing_x - x >= self.landing_regression_px
            or disp < self.jump_min_ratio * step
        ):
            event = dict(p)
            event.update({
                'kind': 'green_outcome',
                'outcome': 'failure',
                'outcome_ts': float(now),
                'end_x': x,
                'forward_dx': disp,
                'max_forward_dx': max_disp,
                'crash_reason': 'post_landing_regression',
                'one_jump_valid': True,
            })
            self.failures += 1
            self.provisional = None
            self.rearm_needed = True
            self.rearm_x = x
            self.rearm_since = None
            return [event]

        # Success is granted only while the position REMAINS inside the
        # expected one-jump landing envelope for the entire grace interval.
        if not (
            self.jump_min_ratio * step <= disp <= self.jump_max_ratio * step
        ):
            return []

        if (now - float(p['landing_ts']) >= self.success_grace
                and self._settled_landing(p, chicken, now)):
            event = dict(p)
            event.update({
                'kind': 'green_outcome',
                'outcome': 'success',
                'outcome_ts': float(now),
                'end_x': x,
                'forward_dx': disp,
                'one_jump_valid': True,
            })
            self.successes += 1
            if str(p.get('landing_source','')) == 'target_switch_advance':
                self.target_arrival_successes += 1
            self.step_history.append(float(disp))
            self.provisional = None
            self.rearm_needed = True
            self.rearm_x = x
            self.rearm_since = float(now)
            return [event]

        return []


    def confirm_validated_manual_success(self, chicken, now):
        """Credit a GREEN when the independent manual-jump validator succeeded.

        The main loop already has a stricter, geometry-based manual success
        validator.  In scrolling gameplay a successful jump can trigger a
        viewport pan before the outcome tracker's provisional grace completes,
        which previously erased every GREEN success while failures survived.
        Only bridge the success when this tracker already owns an acted GREEN
        (active/provisional); unrelated manual jumps remain unrelated.
        """
        src = self.active_attempt if self.active_attempt is not None else self.provisional
        if src is None:
            return None
        if not self._settled_landing(src, chicken, now):
            return None
        a = dict(src)
        x = float((chicken or {}).get(
            'cx', a.get('last_x', a.get('landing_x', a.get('max_x', a.get('baseline_x', 0.0))))
        ))
        step = max(80.0, float(a.get('expected_jump_px', self.expected_step())))
        disp = x - float(a.get('baseline_x', x))
        # The caller has already validated a stable one-lane landing. Keep a
        # broad sanity envelope here only to reject coordinate glitches.
        if not (0.55*step <= disp <= 1.45*step):
            return None
        event = dict(a)
        event.update({
            'kind': 'green_outcome',
            'outcome': 'success',
            'outcome_ts': float(now),
            'end_x': x,
            'forward_dx': disp,
            'success_reason': 'validated_manual_lane_success',
        })
        self.successes += 1
        self.step_history.append(float(disp))
        self.active_attempt = None
        self.provisional = None
        self.current_signal = None
        self.pending_signal = None
        self.rearm_needed = True
        self.rearm_x = x
        self.rearm_since = float(now)
        return event


    def _update_rearm(self, chicken, now, state=None):
        if not self.rearm_needed or self.active_attempt is not None or self.provisional is not None:
            if not self.rearm_needed:
                self.rearm_geometry_since=None
                self.rearm_geometry_key=None
            return
        if chicken is None:
            self.rearm_since = None
            self.rearm_geometry_since=None
            self.rearm_geometry_key=None
            return

        # V5.5.3 geometry-based rearm release.
        #
        # Absolute chicken X is not a reliable post-jump stability coordinate
        # because normal game progress/viewport shifts can move X while the
        # chicken is already landed. The supplied V5.5.2 run contained RECHECK
        # episodes lasting ~9 s after progress resets. When current geometry
        # independently proves a fresh, anchored chicken with a valid next lane,
        # release rearm after a short stable dwell instead of waiting for the
        # old screen X to stop changing.
        if state is not None:
            try:
                ratio=float(state.get('target_lane_distance_ratio',999.0))
            except Exception:
                ratio=999.0
            reason=str(state.get('target_lane_lock_reason',''))
            geom_ok=bool(
                state.get('chicken_fresh',True)
                and state.get('chicken_anchor_stable',False)
                and state.get('target_lane_geometry_ok',False)
                and not state.get('tracking_rewarm',False)
                and .68 <= ratio <= 1.35
                and reason in (
                    'HOLD_SAME','HOLD_HYSTERESIS','ARRIVED',
                    'INITIAL','LANDING_WAIT_RECOVERY'
                )
            )
            if geom_ok:
                key=(
                    int(state.get('target_lane_switches',-1)),
                    int(state.get('viewport_rebase_count',0)),
                )
                if key != self.rearm_geometry_key:
                    self.rearm_geometry_key=key
                    self.rearm_geometry_since=float(now)
                elif (
                    self.rearm_geometry_since is not None
                    and now-float(self.rearm_geometry_since)
                        >= self.rearm_geometry_stable
                ):
                    self.rearm_needed=False
                    self.rearm_since=None
                    self.rearm_geometry_since=None
                    self.rearm_geometry_key=None
                    self.rearm_geometry_releases += 1
                    return
            else:
                self.rearm_geometry_since=None
                self.rearm_geometry_key=None

        x = float(chicken.get('cx', 0.0))
        if self.rearm_x is None:
            self.rearm_x = x
            self.rearm_since = float(now)
            return

        if abs(x - self.rearm_x) <= self.stable_dx:
            if self.rearm_since is None:
                self.rearm_since = float(now)
            elif now - float(self.rearm_since) >= self.rearm_stable:
                self.rearm_needed = False
                self.rearm_since = None
                self.rearm_geometry_since=None
                self.rearm_geometry_key=None
        else:
            self.rearm_x = x
            self.rearm_since = None

    def update(self, state, chicken, now):
        now = float(now)
        events = []
        moving = self._moving(chicken)

        # Never register a fresh GREEN while the chicken is moving/rearming.
        can_register_green = (
            not moving
            and not self.rearm_needed
            and self.active_attempt is None
            and self.provisional is None
            # Do not stack a fresh signal on top of an unacted signal that is
            # still inside its attribution grace. This was producing rapid
            # repeated GREENs when CLEAR flickered for a frame.
            and self.pending_signal is None
        )
        green = bool(
            state.get('indicator_state') == 'CLEAR'
            and state.get('green_confirmed', True)
        )

        if green and can_register_green:
            if self.current_signal is None:
                self.recent_expired_signal = None
                self.current_signal = self._snapshot(state, chicken, now)
                events.append(dict(kind='green_signal_started',
                    signal_id=self.current_signal['signal_id'],event_ts=now,
                    start_ts=now,target_switches_at_signal=state.get('target_lane_switches'),
                    v5_cycle_id=state.get('dynamic_gap_cycle_id')))
                self.green_signals += 1
                self.next_signal_id += 1
            else:
                self.current_signal['end_ts'] = now
                self.current_signal['duration'] = now - self.current_signal['start_ts']
                self.current_signal['eta'] = state.get('effective_eta')
                self.current_signal['raw_risk'] = state.get('raw_risk', state.get('risk'))
                self.current_signal['display_risk'] = state.get('display_risk')
        elif self.current_signal is not None and (not green or not can_register_green):
            self.current_signal['end_ts'] = now
            self.current_signal['duration'] = now - self.current_signal['start_ts']
            self.pending_signal = self.current_signal
            self.current_signal = None

        progress_started = self._progress_handoff_if_needed(state, chicken, now)
        if progress_started:
            events.append(progress_started)

        started = None if progress_started else self._start_action_if_needed(chicken, now, state)
        if started:
            events.append(started)

        early_reset = self._early_input_reset(state, chicken, now)
        if early_reset is not None:
            events.append(early_reset)
        missing_timeout = self._expire_missing_attempt(chicken, now)
        if missing_timeout is not None:
            events.append(missing_timeout)
        else:
            arrival_success = self._target_arrival_success(state, chicken, now)
            if arrival_success is not None:
                events.append(arrival_success)
            else:
                events.extend(self._attempt_progress(chicken, now))
                events.extend(self._provisional_progress(chicken, now))
        self._expire_signal(now)
        self._update_rearm(chicken, now, state)
        events.extend(self.signal_diagnostics)
        self.signal_diagnostics.clear()
        return events

    def on_crash(self, crash_event, now=None):
        """Resolve only CAUSALLY OBSERVED GREEN actions.

        V5.3.7 still had a legacy 6-second crash fallback that fabricated
        ``action_start_ts = green_end`` when no action was ever observed. That
        converted unrelated later crashes/fullscreen reframes into GREEN
        failures. V5.3.8 removes that label path completely.

        A crash can become a GREEN failure only when ``active_attempt`` or
        ``provisional`` already proves that the chicken actually moved in
        response to that GREEN. Even then, one GREEN owns one jump only:
        progress beyond the chain envelope is CHAINED/UNVALIDATED, never a
        supervised GREEN failure.
        """
        now = float(crash_event.get('event_time', now if now is not None else 0.0))

        src = self.active_attempt if self.active_attempt is not None else self.provisional
        if src is None:
            # Diagnostic only. Never invent a GREEN action from crash geometry.
            sig = (self.current_signal or self.pending_signal or self.recent_expired_signal)
            if sig is not None:
                self.crash_fallback_ignored += 1

            self.current_signal = None
            self.pending_signal = None
            self.recent_expired_signal = None
            self.rearm_needed = True
            self.rearm_x = None
            self.rearm_since = None
            if sig is not None:
                return dict(sig,kind='green_outcome',outcome='unknown',
                    outcome_ts=now,unknown_reason='reset_without_observed_action',
                    crash_reason=crash_event.get('reason','unknown'),one_jump_valid=False)
            return None

        if src.get('input_owned') and not src.get('input_movement_seen'):
            event=dict(src,kind='green_outcome',outcome='unknown',outcome_ts=now,
                       unknown_reason='input_without_confirmed_movement',one_jump_valid=False)
            self.active_attempt=None;self.provisional=None
            return event

        # CrashDetector confirms later but timestamps the FIRST reset frame.
        # It cannot resolve an attempt inferred after that reset had started.
        if now < float(src.get('action_start_ts',now)):
            event=dict(src)
            event.update(kind='green_outcome',outcome='unknown',outcome_ts=now,
                         unknown_reason='reset_precedes_action',one_jump_valid=False,
                         crash_reason=crash_event.get('reason','unknown'))
            self.active_attempt=None
            self.provisional=None
            self.current_signal=None
            self.pending_signal=None
            self.recent_expired_signal=None
            self.rearm_needed=True
            self.rearm_x=None
            self.rearm_since=None
            return event

        a = dict(src)
        baseline = float(a.get('baseline_x', 0.0))
        step = max(80.0, float(a.get('expected_jump_px', self.expected_step())))

        if str(a.get('landing_source','')) == 'progress_scroll_handoff':
            a.update({
                'kind':'green_outcome',
                'outcome':'failure',
                'outcome_ts':float(now),
                'end_x':float(a.get('progress_landing_x',a.get('landing_x',0.0))),
                'forward_dx':float(step),
                'max_forward_dx':float(step),
                'crash_reason':crash_event.get('reason','unknown'),
                'one_jump_valid':True,
            })
            self.failures += 1
            self.active_attempt=None
            self.provisional=None
            self.current_signal=None
            self.pending_signal=None
            self.recent_expired_signal=None
            self.rearm_needed=True
            self.rearm_x=None
            self.rearm_since=None
            return a
        observed_peak = max(
            float(a.get('max_x', baseline)),
            float(a.get('last_x', baseline)),
            float(a.get('landing_x', baseline)),
            # A detector peak can span earlier jumps and camera coordinates.
            # Input-owned attempts maintain their own observed trajectory.
            (baseline if a.get('input_owned') else
             float(crash_event.get('max_x', baseline) or baseline)),
        )
        max_forward = observed_peak - baseline

        # If more than one jump has occurred, this crash cannot be blamed on
        # the original GREEN even if it happens shortly afterwards.
        if max_forward > self.chain_ratio * step:
            a.update({
                'kind': 'green_outcome',
                'outcome': 'chained_unvalidated',
                'outcome_ts': now,
                'end_x': float(crash_event.get('reset_x', a.get('last_x', baseline)) or baseline),
                'forward_dx': max_forward,
                'max_forward_dx': max_forward,
                'one_jump_valid': False,
                'crash_reason': 'multi_jump_before_crash',
            })
            self.chained += 1
            self.multi_jump_unvalidated += 1
            self.active_attempt = None
            self.provisional = None
            self.current_signal = None
            self.pending_signal = None
            self.recent_expired_signal = None
            self.rearm_needed = True
            self.rearm_x = None
            self.rearm_since = None
            return a

        end_x = float(a.get(
            'last_x',
            a.get('landing_x', a.get('max_x', a.get('baseline_x', 0.0)))
        ))
        a.update({
            'kind': 'green_outcome',
            'outcome': 'failure',
            'outcome_ts': now,
            'end_x': end_x,
            'forward_dx': end_x - baseline,
            'max_forward_dx': max_forward,
            'crash_reason': crash_event.get('reason', 'unknown'),
            'one_jump_valid': True,
        })

        self.failures += 1
        self.active_attempt = None
        self.provisional = None
        self.current_signal = None
        self.pending_signal = None
        self.recent_expired_signal = None
        self.rearm_needed = True
        self.rearm_x = None
        self.rearm_since = None
        return a

    def block_ui_state(self):
        if self.active_attempt is not None:
            return 'JUMPING'
        if self.provisional is not None:
            return 'VERIFY LAND'
        if self.rearm_needed:
            return 'RECHECK'
        return None

    def status(self):
        return {
            'green_signals': self.green_signals,
            'acted_signals': self.acted_signals,
            'green_successes': self.successes,
            'green_failures': self.failures,
            'green_outcome_successes': self.successes,
            'green_outcome_failures': self.failures,
            'visible_green_signal_id': (
                None if self.current_signal is None else self.current_signal.get('signal_id')
            ),
            'pending_green_signal_id': (
                None if self.pending_signal is None else self.pending_signal.get('signal_id')
            ),
            'green_viewport_rebases': self.viewport_rebases,
            'green_unacted': self.unacted,
            'green_late_unattributed': self.late_unattributed,
            'green_viewport_invalidated': self.viewport_invalidated,
            'green_crash_fallback_ignored': self.crash_fallback_ignored,
            'green_multi_jump_unvalidated': self.multi_jump_unvalidated,
            'green_target_arrival_successes': self.target_arrival_successes,
            'green_progress_handoffs': self.progress_handoffs,
            'post_green_action_grace': self.post_green_action_grace,
            'green_chained': self.chained,
            'active_green_attempt': int(self.active_attempt is not None),
            'provisional_green_landing': int(self.provisional is not None),
            'rearm_needed': int(self.rearm_needed),
            'green_rearm_geometry_releases': int(self.rearm_geometry_releases),
            'expected_jump_px': self.expected_step(),
        }
