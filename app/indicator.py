import math
import time
from collections import deque
import numpy as np


def required_eta_override_for_state(state):
    """Select the final UI ETA requirement without reapplying legacy V4 ETA.

    V5 safe-window already chose a provenance-aware hardcore ETA.  When V5 is
    the active signal source, that value is authoritative for the indicator.
    Legacy sources continue to use green_required_eta unchanged.
    """
    if str(state.get('eta_source','')).lower() == 'v5-safe-window':
        v=state.get('v5_required_eta')
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    v=state.get('green_required_eta')
    try:
        return None if v is None else float(v)
    except Exception:
        return None


class StableRiskIndicator:
    """Stable risk state with time gating + explicit ETA gate.

    CLEAR is allowed only when:
      * low/stable risk has persisted for stable_low_seconds,
      * no visible threat is active,
      * no recent high-risk cooldown is active,
      * and the next-car ETA is known and >= min_clear_eta_seconds
        (unless allow_clear_without_eta is explicitly enabled).
    """

    def __init__(self, cfg):
        self.green_threshold = float(cfg.get('green_threshold', 24))
        self.green_exit_threshold = float(cfg.get('green_exit_threshold', 38))
        self.yellow_threshold = float(cfg.get('yellow_threshold', 45))
        self.red_threshold = float(cfg.get('red_threshold', 72))

        self.volatility_window = float(cfg.get('volatility_window_seconds', 0.9))
        self.stable_low_seconds = float(cfg.get('stable_low_seconds', 0.65))
        self.max_green_stddev = float(cfg.get('max_green_stddev', 15))
        self.green_percentile_limit = float(cfg.get('green_percentile_limit', 34))

        self.high_trigger = float(cfg.get('high_risk_trigger', 75))
        self.high_cooldown = float(cfg.get('high_risk_cooldown_seconds', 0.55))
        self.decay_tau = float(cfg.get('display_decay_seconds', 0.32))

        self.min_clear_eta = float(cfg.get('min_clear_eta_seconds', 1.25))
        self.min_clear_eta_visible = float(cfg.get('min_clear_eta_visible_seconds', 1.35))
        self.min_clear_eta_clearzone = float(cfg.get('min_clear_eta_clearzone_seconds', 1.20))
        self.min_clear_eta_pattern = float(cfg.get('min_clear_eta_pattern_seconds', 1.40))
        self.allow_clear_without_eta = bool(cfg.get('allow_clear_without_eta', False))
        self.clear_hold_seconds = float(cfg.get('clear_hold_seconds', 0.45))
        self.evidence_stable_seconds = float(
            cfg.get('evidence_stable_seconds', .90)
        )
        self.evidence_dropout_grace = float(
            cfg.get('evidence_dropout_grace_seconds', .34)
        )
        self.slow_before_evidence_seconds = float(
            cfg.get('slow_before_evidence_seconds', .22)
        )
        self.slow_after_evidence_seconds = float(
            cfg.get('slow_after_evidence_seconds', .16)
        )
        self.motion_slow_evidence_seconds = float(
            cfg.get('motion_slow_evidence_seconds', .14)
        )
        self.gap_open_stable_seconds = float(
            cfg.get('gap_open_stable_seconds', .08)
        )
        self.gap_open_evidence_seconds = float(
            cfg.get('gap_open_evidence_seconds', .08)
        )
        self.dynamic_gap_stable_seconds = float(
            cfg.get('dynamic_gap_stable_seconds', 0.0)
        )
        self.dynamic_gap_evidence_seconds = float(
            cfg.get('dynamic_gap_evidence_seconds', 0.0)
        )
        self.dynamic_gap_clear_hold_seconds = float(
            cfg.get('dynamic_gap_clear_hold_seconds', 0.0)
        )
        self.last_evidence_good = None

        self.history = deque(maxlen=300)
        self.safe_since = None
        self.evidence_since = None
        self.last_evidence_key = None
        self.high_until = 0.0
        self.display_risk = 50.0
        self.last_ts = None
        self.state = 'UNSTABLE'
        self.clear_hold_until = 0.0
        self.transition_active_key = None
        self.transition_consumed_key = None

    def update(self, raw_risk, visible_threat=False, eta=None, eta_source='unknown',
               external_gate_ok=True, external_block_reason='',
               required_eta_override=None, evidence_key=None, now=None):
        now = float(now if now is not None else time.perf_counter())
        raw = float(np.clip(raw_risk, 0, 100))

        if self.last_ts is None:
            self.display_risk = raw
        else:
            dt = max(0.0, now - self.last_ts)
            decayed = self.display_risk * math.exp(-dt / max(0.05, self.decay_tau))
            self.display_risk = max(raw, decayed)
        self.last_ts = now

        self.history.append((now, raw))
        keep = max(self.volatility_window, self.high_cooldown, self.stable_low_seconds, 1.5) + 0.5
        while self.history and now - self.history[0][0] > keep:
            self.history.popleft()

        if visible_threat or raw >= self.high_trigger:
            self.high_until = max(self.high_until, now + self.high_cooldown)
            self.safe_since = None

        vals = [r for ts, r in self.history if now - ts <= self.volatility_window]
        mean = float(np.mean(vals)) if vals else raw
        std = float(np.std(vals)) if vals else 0.0
        vmax = float(np.max(vals)) if vals else raw
        vmin = float(np.min(vals)) if vals else raw
        p90 = float(np.percentile(vals, 90)) if vals else raw

        cooldown = now < self.high_until

        eta_known = eta is not None and np.isfinite(float(eta))
        eta_value = None if not eta_known else max(0.0, float(eta))
        eta_src = str(eta_source or 'unknown').lower()

        if eta_src == 'visible':
            required_eta = self.min_clear_eta_visible
        elif eta_src == 'clear-zone':
            required_eta = self.min_clear_eta_clearzone
        elif eta_src == 'pattern':
            required_eta = self.min_clear_eta_pattern
        elif eta_src in (
            'slow-before','slow-after','confirmed-slow-after',
            'gap-open','dynamic-gap'
        ):
            required_eta = self.min_clear_eta
        else:
            required_eta = self.min_clear_eta

        if required_eta_override is not None:
            try:
                required_eta = float(required_eta_override)
            except Exception:
                pass

        eta_gate_ok = (
            (eta_known and eta_value >= required_eta)
            or (not eta_known and self.allow_clear_without_eta)
        )

        transition_source = eta_src == 'dynamic-gap'

        if eta_src == 'v5-safe-window':
            # V5 has already combined the soft risk/ETA/motion evidence into a
            # calibrated safe-window probability and separately enforced its
            # hard physical/vision vetoes. Do not run that decision back through
            # the legacy V4 green-risk threshold, otherwise V5-approved windows
            # are silently rejected (the V5.0 zero-GREEN integration bug).
            low_now = not visible_threat
        elif transition_source:
            # A dynamic gap starts immediately after a high-risk vehicle passes.
            # The trailing volatility/cooldown is therefore expected evidence
            # of the transition, not a reason to wait until the gap is gone.
            # Safety is carried by the risk engine's forward hazard horizon.
            low_now = (
                raw < self.green_threshold
                and not visible_threat
            )
        else:
            low_now = (
                raw < self.green_threshold
                and mean < self.green_exit_threshold
                and p90 < self.green_percentile_limit
                and std <= self.max_green_stddev
                and not cooldown
                and not visible_threat
            )

        if low_now:
            if self.safe_since is None:
                self.safe_since = now
        else:
            self.safe_since = None

        safe_elapsed = 0.0 if self.safe_since is None else max(0.0, now - self.safe_since)
        stability_required = self.stable_low_seconds
        if eta_src == 'gap-open':
            stability_required = min(
                stability_required,self.gap_open_stable_seconds
            )
        elif eta_src == 'dynamic-gap':
            stability_required = min(
                stability_required,self.dynamic_gap_stable_seconds
            )
        elif eta_src == 'v5-safe-window':
            stability_required = 0.0
        stability_ready = safe_elapsed >= stability_required

        ev_key = str(evidence_key if evidence_key is not None else eta_src)
        evidence_good_now = bool(
            low_now and eta_gate_ok and external_gate_ok and not visible_threat
        )
        if ev_key != self.last_evidence_key:
            self.evidence_since = None
            self.last_evidence_key = ev_key

        if evidence_good_now:
            self.last_evidence_good = now
            if self.evidence_since is None:
                self.evidence_since = now
        else:
            dropout_age = (1e9 if self.last_evidence_good is None
                           else max(0.0,now-self.last_evidence_good))
            if dropout_age > self.evidence_dropout_grace:
                self.evidence_since = None

        evidence_elapsed = (
            0.0 if self.evidence_since is None
            else max(0.0, now - self.evidence_since)
        )
        evidence_required = self.evidence_stable_seconds
        if eta_src == 'slow-before':
            evidence_required = min(
                evidence_required, self.slow_before_evidence_seconds
            )
        elif eta_src == 'slow-after':
            evidence_required = min(
                evidence_required, self.slow_after_evidence_seconds
            )
        elif eta_src == 'confirmed-slow-after':
            evidence_required = min(
                evidence_required, self.motion_slow_evidence_seconds
            )
        elif eta_src == 'gap-open':
            evidence_required = min(
                evidence_required,self.gap_open_evidence_seconds
            )
        elif eta_src == 'dynamic-gap':
            evidence_required = min(
                evidence_required,self.dynamic_gap_evidence_seconds
            )
        elif eta_src == 'v5-safe-window':
            evidence_required = 0.0
        evidence_ready = evidence_elapsed >= evidence_required

        green_confirmed = bool(
            stability_ready and eta_gate_ok and external_gate_ok and evidence_ready
        )

        danger_now = (
            visible_threat
            or raw >= self.red_threshold
            or (eta_known and eta_value < required_eta)
        )

        # Dynamic-gap CLEAR is a one-shot permission for one physical gap.
        # If that CLEAR ends because evidence flickers, do not announce the
        # same busy->clear cycle again. A new cycle_id in evidence_key rearms it.
        if transition_source and self.transition_active_key is not None:
            if ev_key != self.transition_active_key or not green_confirmed:
                self.transition_consumed_key = self.transition_active_key
                self.transition_active_key = None
        transition_reused = bool(
            transition_source
            and self.transition_consumed_key == ev_key
            and self.transition_active_key != ev_key
        )
        if transition_reused:
            green_confirmed = False

        if danger_now:
            self.clear_hold_until = 0.0
            state = 'WAIT' if (visible_threat or raw >= self.red_threshold) else 'ETA HOLD'
            block_reason = 'VISIBLE/HIGH RISK' if state == 'WAIT' else f'ETA {eta_value:.2f}s < {required_eta:.2f}s'
        elif not external_gate_ok:
            self.clear_hold_until = 0.0
            state = 'CHECKING'
            block_reason = str(external_block_reason or 'EVIDENCE NOT READY')
        elif green_confirmed:
            if transition_source:
                self.transition_active_key = ev_key
            source_hold=(
                self.dynamic_gap_clear_hold_seconds
                if eta_src=='dynamic-gap'
                else self.clear_hold_seconds
            )
            self.clear_hold_until=max(
                self.clear_hold_until,now+source_hold
            )
            state='CLEAR'
            block_reason=''
        elif transition_reused:
            self.clear_hold_until = 0.0
            state = 'ETA HOLD'
            block_reason = 'GAP ALREADY SIGNALED - WAIT NEXT VEHICLE'
        elif external_gate_ok and eta_gate_ok and stability_ready and not evidence_ready:
            self.clear_hold_until = 0.0
            state = 'CHECKING'
            block_reason = (
                f"VERIFY {evidence_elapsed:.1f}/{evidence_required:.1f}s"
            )
        elif now < self.clear_hold_until and eta_src != 'dynamic-gap':
            state='CLEAR'
            block_reason=''
            green_confirmed=True
        elif stability_ready and not eta_gate_ok:
            state = 'ETA HOLD'
            block_reason = 'ETA UNKNOWN' if not eta_known else f'ETA {eta_value:.2f}s < {required_eta:.2f}s'
        elif (
            not transition_source
            and (
                cooldown
                or std > self.max_green_stddev
                or (vmax-vmin) > 30
            )
        ):
            state = 'UNSTABLE'
            block_reason = 'RISK VOLATILITY'
        elif raw >= self.yellow_threshold:
            state = 'CAUTION'
            block_reason = 'MODERATE RISK'
        else:
            state = 'CHECKING'
            block_reason = 'CONFIRMING STABILITY'

        shown = max(raw, self.display_risk)
        if green_confirmed:
            shown = raw if transition_source else max(raw, mean)
        if cooldown and state != 'WAIT':
            shown = max(shown, self.green_exit_threshold)

        self.state = state
        return {
            'indicator_state': state,
            'display_risk': float(np.clip(shown, 0, 99)),
            'raw_risk': raw,
            'risk_mean': mean,
            'risk_std': std,
            'risk_max': vmax,
            'risk_p90': p90,
            'stable_samples': len(vals),
            'stable_low_elapsed': safe_elapsed,
            'stable_low_required': stability_required,
            'evidence_stable_elapsed': evidence_elapsed,
            'evidence_stable_required': evidence_required,
            'evidence_ready': bool(evidence_ready),
            'evidence_key': ev_key,
            'green_confirmed': green_confirmed,
            'high_cooldown': bool(cooldown),
            'eta_gate_ok': bool(eta_gate_ok),
            'clear_eta': eta_value,
            'eta_source_for_gate': eta_src,
            'required_clear_eta': required_eta,
            'clear_block_reason': block_reason,
            'external_gate_ok': bool(external_gate_ok),
        }
