import math
import time
from collections import deque
import numpy as np


class AdaptiveSessionModel:
    """Live traffic-regime calibration for the immediate next-lane decision.

    Long-term pattern memory lives in OnlineLearner.  This object intentionally
    models only *current-session/current-regime* conditions so a refresh, crash,
    or traffic-speed change can alter the GREEN requirement without editing JSON.
    """

    def __init__(self, cfg):
        self.short_window = float(cfg.get('adaptive_short_window_seconds', 24.0))
        self.long_window = float(cfg.get('adaptive_long_window_seconds', 75.0))
        self.min_events = int(cfg.get('adaptive_min_events', 6))
        self.regime_gap = float(cfg.get('adaptive_regime_gap_seconds', 7.0))
        self.regime_cooldown = float(cfg.get('adaptive_regime_cooldown_seconds', 12.0))
        self.speed_shift_ratio = float(cfg.get('adaptive_speed_shift_ratio', .22))
        self.headway_shift_ratio = float(cfg.get('adaptive_headway_shift_ratio', .28))
        self.crash_window = float(cfg.get('adaptive_crash_window_seconds', 120.0))
        self.outcome_window = float(cfg.get('adaptive_outcome_window_seconds', 180.0))
        self.post_crash_warmup = float(cfg.get('adaptive_post_crash_warmup_seconds', 5.0))

        # V5.4.4 explicit difficulty-mode controller. The old regime counter was
        # event-driven and could reset after traffic pauses while the gap predictor
        # still remained anchored to old history. Difficulty mode is frame/live-
        # motion driven instead, with hysteresis: hardening happens quickly, easing
        # requires sustained evidence so one lucky gap cannot make the model loose.
        self.mode_ema_tau = float(cfg.get('difficulty_mode_ema_seconds', 3.0))
        self.mode_harder_dwell = float(cfg.get('difficulty_mode_harder_dwell_seconds', 1.2))
        self.mode_easier_dwell = float(cfg.get('difficulty_mode_easier_dwell_seconds', 5.0))
        self.mode_easy_max = float(cfg.get('difficulty_mode_easy_max_score', .30))
        self.mode_normal_max = float(cfg.get('difficulty_mode_normal_max_score', .52))
        self.mode_hard_max = float(cfg.get('difficulty_mode_hard_max_score', .73))
        self.mode_hysteresis = float(cfg.get('difficulty_mode_hysteresis', .04))
        self.mode_extreme_hysteresis = float(cfg.get('difficulty_mode_extreme_hysteresis', .05))
        self.difficulty_mode = 'NORMAL'
        self.difficulty_score = .45
        self.difficulty_raw_score = .45
        self.mode_candidate = self.difficulty_mode
        self.mode_candidate_since = time.time()
        self.mode_started = self.mode_candidate_since
        self.mode_switches = 0
        self.last_mode_update = self.mode_candidate_since
        self.mode_reason = 'startup'

        self.base_eta_visible = float(cfg.get('adaptive_base_eta_visible_seconds', 1.05))
        self.base_eta_czn = float(cfg.get('adaptive_base_eta_czn_seconds', 1.03))
        self.base_eta_pattern = float(cfg.get('adaptive_base_eta_pattern_seconds', 1.10))
        self.eta_floor = float(cfg.get('adaptive_eta_floor_seconds', .92))
        self.eta_ceiling = float(cfg.get('adaptive_eta_ceiling_seconds', 2.10))
        self.base_clear_dwell = float(cfg.get('adaptive_base_clear_dwell_seconds', .24))
        self.max_clear_dwell = float(cfg.get('adaptive_max_clear_dwell_seconds', .78))
        self.base_confidence = float(cfg.get('adaptive_base_confidence', .74))
        self.min_chicken_conf = float(cfg.get('adaptive_min_chicken_confidence', .45))

        self.regime_id = 1
        self.regime_started = time.time()
        self.regime_reason = 'startup'
        self.last_regime_change = self.regime_started
        self.last_processed_event_ts = None
        self.crashes = deque(maxlen=100)
        self.outcomes = deque(maxlen=200)
        self.last_metrics = {}

    @staticmethod
    def _clip(x, lo, hi):
        return float(max(lo, min(hi, x)))

    @staticmethod
    def _sigmoid(x):
        if x >= 0:
            z = math.exp(-x)
            return 1.0 / (1.0 + z)
        z = math.exp(x)
        return z / (1.0 + z)

    def _new_regime(self, now, reason):
        now = float(now)
        if now - self.last_regime_change < 1.0:
            return
        self.regime_id += 1
        self.regime_started = now
        self.last_regime_change = now
        self.regime_reason = str(reason)

    def on_crash(self, now=None, reason='crash'):
        now = float(now if now is not None else time.time())
        self.crashes.append((now, str(reason)))

        # V4.3.4: a chicken death does not imply traffic distribution changed.
        # Resetting the regime on every death left regime_samples near zero for
        # the entire run.  Real regime changes are still detected statistically
        # by observe_traffic().

    def on_outcome(self, outcome, now=None):
        if not outcome:
            return
        status = str(outcome.get('outcome', 'unknown'))
        if status not in ('success', 'failure'):
            return
        now = float(outcome.get('outcome_ts', now if now is not None else time.time()))
        self.outcomes.append((
            now, status, str(outcome.get('eta_source', 'unknown')),
            str(outcome.get('speed_pattern', '-'))
        ))

    def _event_speed(self, e, slow_thr, fast_thr):
        v = e.get('speed')
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
        cls = str(e.get('class', 'M'))
        if cls == 'S':
            return max(20.0, slow_thr * .72)
        if cls == 'F':
            return max(fast_thr * 1.18, fast_thr + 20.0)
        return (slow_thr + fast_thr) / 2.0

    def _window_events(self, events, now, seconds):
        lo = float(now) - float(seconds)
        return [e for e in events if float(e.get('ts', 0.0)) >= lo and e.get('token') != '<RESET>']

    def _metrics(self, events, now, slow_thr, fast_thr):
        ev = self._window_events(events, now, self.long_window)
        short = self._window_events(events, now, self.short_window)
        use = short if len(short) >= self.min_events else ev

        speeds = np.asarray([
            self._event_speed(e, slow_thr, fast_thr) for e in use
        ], dtype=float) if use else np.asarray([], dtype=float)
        gaps = np.asarray([
            float(e['gap']) for e in use
            if e.get('gap') is not None and .18 <= float(e['gap']) <= 5.0
        ], dtype=float) if use else np.asarray([], dtype=float)

        classes = [str(e.get('class','M')) for e in use]
        n = len(use)
        speed_p90 = float(np.percentile(speeds, 90)) if len(speeds) else float(fast_thr)
        speed_p50 = float(np.median(speeds)) if len(speeds) else float((slow_thr+fast_thr)/2.0)
        gap_p25 = float(np.percentile(gaps, 25)) if len(gaps) else 1.25
        gap_med = float(np.median(gaps)) if len(gaps) else 1.50
        gap_cv = float(np.std(gaps) / max(.20, np.mean(gaps))) if len(gaps) >= 3 else .55
        fast_fraction = (sum(c == 'F' for c in classes) / n) if n else .33

        return {
            'events': n,
            'speed_p90': speed_p90,
            'speed_p50': speed_p50,
            'gap_p25': gap_p25,
            'gap_median': gap_med,
            'gap_cv': gap_cv,
            'fast_fraction': float(fast_fraction),
            'short_events': len(short),
        }

    def observe_traffic(self, events, now, slow_thr, fast_thr):
        """Update regime boundaries and return current traffic metrics."""
        now = float(now)
        events = list(events or [])
        latest_ts = max((float(e.get('ts', 0.0)) for e in events if e.get('token') != '<RESET>'), default=None)

        if latest_ts is not None and (self.last_processed_event_ts is None or latest_ts > self.last_processed_event_ts + 1e-6):
            # V5.4.4: a quiet interval is NOT a traffic regime change. Resetting
            # here made regime_samples live near zero and destroyed the meaning of
            # the adaptive regime telemetry. Statistical distribution shifts below
            # remain authoritative.
            self.last_processed_event_ts = latest_ts

        m = self._metrics(events, now, slow_thr, fast_thr)

        # Detect an actual statistical regime change only on a new event and
        # only after the cooldown. Compare recent traffic to the older part of
        # the long window so ordinary noise does not cause regime flapping.
        if (
            latest_ts is not None
            and now - self.last_regime_change >= self.regime_cooldown
            and len(events) >= 16
        ):
            recent = self._window_events(events, now, min(self.short_window, 18.0))
            older = [e for e in self._window_events(events, now, self.long_window)
                     if float(e.get('ts', 0.0)) < now - min(self.short_window, 18.0)]
            if len(recent) >= 7 and len(older) >= 8:
                mr = self._metrics(recent, now, slow_thr, fast_thr)
                # For older we use a synthetic 'now' at its newest sample to
                # avoid re-windowing it away.
                old_now = max(float(e.get('ts', 0.0)) for e in older)
                mo = self._metrics(older, old_now, slow_thr, fast_thr)
                speed_shift = abs(mr['speed_p90'] - mo['speed_p90']) / max(80.0, mo['speed_p90'])
                gap_shift = abs(mr['gap_p25'] - mo['gap_p25']) / max(.35, mo['gap_p25'])
                if speed_shift >= self.speed_shift_ratio or gap_shift >= self.headway_shift_ratio:
                    self._new_regime(now, 'traffic_distribution_shift')

        m['regime_id'] = self.regime_id
        m['regime_age'] = max(0.0, now - self.regime_started)
        m['regime_reason'] = self.regime_reason
        m['regime_samples'] = sum(
            1 for e in events if float(e.get('ts', 0.0)) >= self.regime_started and e.get('token') != '<RESET>'
        )
        self.last_metrics = m
        return m

    def update_difficulty_mode(self, now, motion_profile, speed_score, density_score, traffic=None):
        """Update EASY/NORMAL/HARD/EXTREME from live traffic evidence.

        The score is intentionally dominated by headway/density rather than raw
        speed: fast sparse traffic can still have excellent jump windows, while
        slower dense traffic can be difficult. Motion-gap history is available
        even when tracker crossing events are sparse, so this controller does not
        freeze when the event learner goes quiet.
        """
        now=float(now)
        mp=motion_profile or {}
        support=int(mp.get('support',0) or 0)
        p25=mp.get('recent_p25') if int(mp.get('recent_support',0) or 0) >= 6 else mp.get('p25')
        if p25 is not None and support >= 6:
            gap_score=self._clip((2.20-float(p25))/1.20,0.0,1.0)
        else:
            tp=(traffic or {}).get('gap_p25') if traffic else None
            gap_score=self._clip((2.10-float(tp))/1.15,0.0,1.0) if tp not in (None,0) else .50
        cv=float(mp.get('gap_cv',.55) or .55)
        volatility=self._clip((cv-.40)/.70,0.0,1.0)
        busy=float(mp.get('busy_fraction',0.0) or 0.0)
        busy_score=self._clip((busy-.10)/.42,0.0,1.0)
        speed=self._clip(float(speed_score or 0.0),0.0,1.0)
        density=max(self._clip(float(density_score or 0.0),0.0,1.0),busy_score)

        raw=self._clip(.50*gap_score + .27*speed + .15*density + .08*volatility,0.0,1.0)
        dt=max(.01,min(1.0,now-float(self.last_mode_update)))
        self.last_mode_update=now
        alpha=1.0-math.exp(-dt/max(.25,self.mode_ema_tau))
        self.difficulty_score=float((1.0-alpha)*self.difficulty_score + alpha*raw)
        self.difficulty_raw_score=float(raw)

        score=self.difficulty_score
        h=self.mode_hysteresis
        hx=self.mode_extreme_hysteresis

        # V5.4.6 FAST-TRAFFIC MODE FLOOR.
        # Headway is still the main difficulty signal, but this run proved that
        # very fast traffic could remain EASY merely because the average gap was
        # generous. A fast car returning during the user's click->jump latency
        # can still make that state hazardous. Force a minimum mode from current
        # speed+density evidence while retaining hysteresis for actual switching.
        mode_floor='EASY'
        if speed >= .92 and (density >= .16 or busy >= .18):
            mode_floor='HARD'
        elif speed >= .75 and (density >= .18 or busy >= .20):
            mode_floor='HARD'
        elif speed >= .72 or density >= .36 or busy >= .28:
            mode_floor='NORMAL'
        # Stateful hysteresis avoids NORMAL<->HARD flapping when the score sits
        # on a boundary. Transitions are one adjacent mode at a time.
        if self.difficulty_mode == 'EASY':
            desired='NORMAL' if score >= self.mode_easy_max+h else 'EASY'
        elif self.difficulty_mode == 'NORMAL':
            if score <= self.mode_easy_max-h:
                desired='EASY'
            elif score >= self.mode_normal_max+h:
                desired='HARD'
            else:
                desired='NORMAL'
        elif self.difficulty_mode == 'HARD':
            if score <= self.mode_normal_max-h:
                desired='NORMAL'
            elif score >= self.mode_hard_max+hx:
                desired='EXTREME'
            else:
                desired='HARD'
        else:
            desired='HARD' if score <= self.mode_hard_max-hx else 'EXTREME'
        order={'EASY':0,'NORMAL':1,'HARD':2,'EXTREME':3}
        if order.get(mode_floor,0) > order.get(desired,0):
            desired=mode_floor
        if desired != self.mode_candidate:
            self.mode_candidate=desired
            self.mode_candidate_since=now
        if desired != self.difficulty_mode:
            harder=order[desired] > order[self.difficulty_mode]
            dwell=self.mode_harder_dwell if harder else self.mode_easier_dwell
            if now-self.mode_candidate_since >= dwell:
                old=self.difficulty_mode
                self.difficulty_mode=desired
                self.mode_started=now
                self.mode_switches += 1
                self.mode_reason=f'{old}->{desired}'
        else:
            self.mode_candidate_since=now

        return {
            'mode':self.difficulty_mode,
            'score':float(self.difficulty_score),
            'raw_score':float(raw),
            'candidate':self.mode_candidate,
            'candidate_age':max(0.0,now-self.mode_candidate_since),
            'age':max(0.0,now-self.mode_started),
            'switches':int(self.mode_switches),
            'reason':self.mode_reason,
            'gap_score':float(gap_score),
            'speed_score':float(speed),
            'density_score':float(density),
            'volatility_score':float(volatility),
            'mode_floor':str(mode_floor),
        }


    def _recent_feedback(self, now, eta_source=None):
        now = float(now)
        while self.crashes and now - self.crashes[0][0] > self.crash_window:
            self.crashes.popleft()
        while self.outcomes and now - self.outcomes[0][0] > self.outcome_window:
            self.outcomes.popleft()

        successes = 0
        failures = 0
        source_s = 0
        source_f = 0
        for ts, status, source, pattern in self.outcomes:
            if status == 'success': successes += 1
            elif status == 'failure': failures += 1
            if eta_source is not None and source == eta_source:
                if status == 'success': source_s += 1
                elif status == 'failure': source_f += 1

        # Smoothed short-term reliability.  No data starts neutral rather than
        # overconfident.
        rel = (successes + 4.0) / (successes + failures + 5.0)
        src_rel = (source_s + 4.0) / (source_s + source_f + 5.0)
        return {
            'crashes': len(self.crashes),
            'successes': successes,
            'failures': failures,
            'source_successes': source_s,
            'source_failures': source_f,
            'reliability': float(rel),
            'source_reliability': float(src_rel),
        }

    def assess(self, *, now, eta_source, eta, direct_risk, overall_risk,
               visibility_ok, visibility_score, visible_threat, clear_dwell,
               recent_threat_age, pattern, chicken_conf, traffic,
               source_reliability, jump_time, safety_buffer):
        now = float(now)
        fb = self._recent_feedback(now, eta_source)

        if eta_source == 'visible':
            base_eta = self.base_eta_visible
        elif eta_source in ('clear-zone','fused'):
            base_eta = self.base_eta_czn
        elif eta_source == 'pattern':
            base_eta = self.base_eta_pattern
        else:
            base_eta = self.base_eta_visible

        # Headway and volatility are the main dynamic corrections.  CZN ETA
        # already incorporates current fast-car speed, so avoid double-counting
        # speed too aggressively here.
        gap25 = float(traffic.get('gap_p25', 1.25))
        gap_cv = float(traffic.get('gap_cv', .55))
        fast_frac = float(traffic.get('fast_fraction', .33))
        events = int(traffic.get('events', 0))
        regime_samples = int(traffic.get('regime_samples', 0))
        regime_age = float(traffic.get('regime_age', 0.0))

        headway_adj = self._clip((1.05 - gap25) * .30, -.10, .22)
        volatility_adj = self._clip((gap_cv - .55) * .16, 0.0, .16)
        fast_adj = self._clip((fast_frac - .34) * .18, -.05, .12)
        # Generic crashes are weak global evidence because they can come from
        # manual jumps.  GREEN-attributed failures remain strong evidence.
        generic_crashes = min(2, int(fb['crashes']))
        crash_adj = min(
            .20,
            .012 * generic_crashes + .11 * fb['failures']
        )
        success_relief = min(.12, .025 * max(0, fb['successes'] - fb['failures']))

        # Sparse crossing events must not permanently trap CZN in "warmup".
        # Traffic defaults are already conservative; warmup is now time-based.
        warm = regime_age < self.post_crash_warmup
        warm_adj = .08 if warm else 0.0

        physical_floor = max(self.eta_floor, float(jump_time) + float(safety_buffer) + .08)
        required_eta = self._clip(
            base_eta + headway_adj + volatility_adj + fast_adj + crash_adj + warm_adj - success_relief,
            physical_floor, self.eta_ceiling
        )

        required_dwell = self._clip(
            self.base_clear_dwell
            + max(0.0, gap_cv-.50)*.18
            + .012*generic_crashes
            + .09*fb['failures']
            + (.07 if warm else 0.0)
            - min(.07, .015*fb['successes']),
            .18, self.max_clear_dwell
        )

        pconf = float(pattern.get('confidence', 0.0)) if pattern else 0.0
        psupport = int(pattern.get('support', 0)) if pattern else 0
        pfast = float(pattern.get('p_next_fast', .50)) if pattern else .50
        pp25 = pattern.get('p25_gap') if pattern else None
        pattern_score = .52
        if pattern and pattern.get('ready'):
            support_score = min(1.0, psupport / 10.0)
            fast_score = self._clip(1.0 - pfast, 0.0, 1.0)
            gap_score = self._clip((float(pp25 or .7) - .65) / .85, 0.0, 1.0)
            pattern_score = self._clip(.40*pconf + .30*support_score + .20*fast_score + .10*gap_score, 0.0, 1.0)

            # Historical pattern only receives full credit when it agrees with
            # the current regime's headway distribution.
            if pp25 is not None and events >= self.min_events:
                consistency = math.exp(-abs(float(pp25)-gap25) / max(.28, gap25))
                pattern_score *= (.55 + .45*consistency)

        eta_score = 0.0 if eta is None else self._sigmoid((float(eta)-required_eta)/.15)
        geometry_score = self._clip(1.0 - float(direct_risk)/100.0, 0.0, 1.0)
        visibility_score = self._clip(float(visibility_score), 0.0, 1.0) if visibility_ok else 0.0
        traffic_score = self._clip(
            .50
            + .22*self._clip((gap25-.65)/1.0, 0.0, 1.0)
            - .20*self._clip((gap_cv-.45)/.75, 0.0, 1.0)
            - .12*self._clip((fast_frac-.33)/.45, 0.0, 1.0),
            0.0, 1.0
        )
        outcome_score = .55*fb['reliability'] + .45*float(source_reliability)

        confidence = (
            .29*geometry_score
            + .25*eta_score
            + .15*visibility_score
            + .13*traffic_score
            + .10*outcome_score
            + .08*pattern_score
        )
        confidence -= min(
            .14,
            .008*generic_crashes + .060*fb['failures']
        )
        confidence = self._clip(confidence, 0.0, 1.0)

        required_conf = self._clip(
            self.base_confidence
            + (.04 if warm else 0.0)
            + min(
                .09,
                .005*generic_crashes + .042*fb['failures']
            )
            - min(.05, .012*fb['successes']),
            .70, .86
        )

        ok = True
        reason = ''
        if not visibility_ok:
            ok = False; reason = 'LANE OCCLUDED'
        elif float(chicken_conf or 0.0) < self.min_chicken_conf:
            ok = False; reason = 'CHICKEN UNCERTAIN'
        elif visible_threat:
            ok = False; reason = 'VISIBLE THREAT'
        elif eta is None:
            ok = False; reason = 'ETA UNKNOWN'
        elif float(eta) < required_eta:
            ok = False; reason = f'ADAPT ETA {float(eta):.2f}<{required_eta:.2f}'
        elif eta_source in ('clear-zone','fused') and float(clear_dwell) < required_dwell:
            ok = False; reason = f'ADAPT DWELL {float(clear_dwell):.2f}<{required_dwell:.2f}'
        elif eta_source in ('clear-zone','fused','pattern') and recent_threat_age < min(.45, required_dwell):
            ok = False; reason = 'RECENT THREAT'
        elif eta_source == 'pattern' and (not pattern or not pattern.get('ready') or psupport < 4):
            ok = False; reason = 'WEAK PATTERN'
        elif confidence < required_conf:
            ok = False; reason = f'CONF {int(confidence*100)}<{int(required_conf*100)}'

        return {
            'green_ok': bool(ok),
            'reason': reason,
            'required_eta': float(required_eta),
            'required_dwell': float(required_dwell),
            'confidence': float(confidence),
            'required_confidence': float(required_conf),
            'regime_id': int(self.regime_id),
            'regime_age': float(regime_age),
            'regime_samples': int(regime_samples),
            'regime_reason': self.regime_reason,
            'speed_p90': float(traffic.get('speed_p90', 0.0)),
            'speed_p50': float(traffic.get('speed_p50', 0.0)),
            'gap_p25': float(gap25),
            'gap_median': float(traffic.get('gap_median', 0.0)),
            'gap_cv': float(gap_cv),
            'fast_fraction': float(fast_frac),
            'recent_crashes': int(fb['crashes']),
            'recent_successes': int(fb['successes']),
            'recent_failures': int(fb['failures']),
            'recent_source_successes': int(fb['source_successes']),
            'recent_source_failures': int(fb['source_failures']),
            'recent_reliability': float(fb['reliability']),
            'source_session_reliability': float(fb['source_reliability']),
            'pattern_session_score': float(pattern_score),
            'traffic_score': float(traffic_score),
            'warmup': bool(warm),
        }
