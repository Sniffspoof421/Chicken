from __future__ import annotations

import csv
import json
import math
import time
from collections import deque
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler


class SafeWindowPredictor:
    """V5 online future-clear-window predictor.

    It learns from every observable target-lane state, not just acted GREENs.
    A state is retrospectively labelled SAFE only when the lane stays free of
    a threat for the configured future horizon.  The existing V4 risk engine
    remains the perception/source layer; V5 replaces the stack of soft GREEN
    gates with one calibrated probability plus a small set of hard vetoes.
    """

    FEATURE_NAMES = (
        'eta', 'clear_dwell', 'motion_dwell', 'motion_clear', 'visibility',
        'raw_risk_inv', 'source_rel', 'adaptive_conf', 'gap_p25',
        'dynamic_conf', 'stage_easy', 'recent_rel', 'crash_safe',
        'slow_before', 'slow_after', 'follower_clear', 'slow_after_profile',
        'processing_health'
    )

    def __init__(self, root: Path, cfg: dict):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get('enabled', True))
        self.horizon = float(self.cfg.get('label_horizon_seconds', 1.05))
        self.min_samples = int(self.cfg.get('min_training_samples', 45))
        self.base_threshold = float(self.cfg.get('base_probability_threshold', .84))
        self.easy_threshold = float(self.cfg.get('easy_probability_threshold', .87))
        self.hard_threshold = float(self.cfg.get('hard_probability_threshold', .80))
        self.absolute_eta = float(self.cfg.get('absolute_min_eta_seconds', .92))
        self.verified_gap_min_eta = float(self.cfg.get('verified_gap_min_eta_seconds', self.absolute_eta))
        self.observed_clear_min_eta = float(self.cfg.get('observed_clear_min_eta_seconds', 1.20))
        self.forecast_min_eta = float(self.cfg.get('forecast_min_eta_seconds', 1.28))
        self.forecast_slow_after_eta_penalty = float(self.cfg.get('forecast_slow_after_eta_penalty_seconds', .08))
        self.forecast_slow_after_threshold_penalty = float(self.cfg.get('forecast_slow_after_threshold_penalty', .006))
        self.historical_slow_after_safe_gap = float(self.cfg.get('historical_slow_after_safe_gap_seconds', 1.25))
        self.observed_clear_min_elapsed = float(self.cfg.get('observed_clear_min_elapsed_seconds', .70))
        self.observed_clear_min_gap_p25 = float(self.cfg.get('observed_clear_min_gap_p25_seconds', 1.10))
        self.historical_slow_after_current_gap_floor = float(self.cfg.get('historical_slow_after_current_gap_floor_seconds', 1.25))
        self.historical_slow_after_risk_trigger = float(self.cfg.get('historical_slow_after_risk_trigger', .30))
        # V5.3.1: strong sustained observed-clear evidence may outvote a stale
        # classifier in a new hardcore traffic regime, but only after every
        # hard physical veto has already passed.  A small probability sanity
        # floor remains so the override is not blind.
        self.observed_physical_override_enabled = bool(self.cfg.get('observed_clear_physical_override_enabled', True))
        self.observed_physical_min_elapsed = float(self.cfg.get('observed_clear_physical_min_elapsed_seconds', 1.00))
        self.observed_physical_min_gap_p25 = float(self.cfg.get('observed_clear_physical_min_gap_p25_seconds', 1.05))
        self.observed_physical_eta_margin = float(self.cfg.get('observed_clear_physical_eta_margin_seconds', .05))
        self.observed_physical_max_motion = float(self.cfg.get('observed_clear_physical_max_motion_ratio', .04))
        self.observed_physical_max_mog = float(self.cfg.get('observed_clear_physical_max_mog_ratio', .055))
        self.observed_physical_max_raw = float(self.cfg.get('observed_clear_physical_max_raw_risk', 20.0))
        self.observed_physical_min_probability = float(self.cfg.get('observed_clear_physical_min_probability', .42))
        self.observed_physical_min_difficulty = float(self.cfg.get('observed_clear_physical_min_difficulty', .60))
        self.observed_physical_min_czn_events = int(self.cfg.get('observed_clear_physical_min_czn_events', 2))
        self.observed_physical_strong_gap_p25 = float(self.cfg.get('observed_clear_physical_strong_gap_p25_seconds', 1.55))
        self.observed_physical_strong_gap_support = int(self.cfg.get('observed_clear_physical_strong_gap_support', 12))
        # V5.2.8: provenance-aware confidence floors. ML remains useful as a
        # sanity/ranking signal, but an absolute ~0.90 threshold must not veto
        # every physically clean gap when hardcore traffic changes regime.
        self.verified_prob_easy = float(self.cfg.get('verified_gap_probability_floor_easy', .82))
        self.verified_prob_hard = float(self.cfg.get('verified_gap_probability_floor_hard', .74))
        self.observed_prob_easy = float(self.cfg.get('observed_clear_probability_floor_easy', .85))
        self.observed_prob_hard = float(self.cfg.get('observed_clear_probability_floor_hard', .79))
        self.tracked_prob_easy = float(self.cfg.get('tracked_forecast_probability_floor_easy', .90))
        self.tracked_prob_hard = float(self.cfg.get('tracked_forecast_probability_floor_hard', .86))
        self.slow_before_prob_easy = float(self.cfg.get('slow_before_probability_floor_easy', .84))
        self.slow_before_prob_hard = float(self.cfg.get('slow_before_probability_floor_hard', .78))
        self.physical_slow_risk_prob_penalty = float(self.cfg.get('physical_slow_risk_probability_penalty', .015))
        self.gap_difficulty_easy_seconds = float(self.cfg.get('gap_difficulty_easy_seconds', 1.55))
        self.gap_difficulty_hard_seconds = float(self.cfg.get('gap_difficulty_hard_seconds', .80))
        self.speed_difficulty_weight = float(self.cfg.get('speed_difficulty_weight', .72))
        self.gap_difficulty_weight = float(self.cfg.get('gap_difficulty_weight', .88))
        self.density_difficulty_weight = float(self.cfg.get('density_difficulty_weight', .55))
        self.min_live_gap_p25 = float(self.cfg.get('min_live_gap_p25_seconds', .95))
        self.min_live_gap_support = int(self.cfg.get('min_live_gap_support', 8))
        self.min_preceding_busy = float(self.cfg.get('min_preceding_busy_seconds', .16))
        self.max_motion_ratio = float(self.cfg.get('hard_max_motion_ratio', .105))
        self.max_raw_risk = float(self.cfg.get('hard_max_raw_risk', 45.0))
        self.min_visibility = float(self.cfg.get('hard_min_visibility', .56))
        self.max_mog = float(self.cfg.get('hard_max_mog_ratio', .13))
        self.candidate_interval = float(self.cfg.get('candidate_interval_seconds', .18))
        self.max_pending = int(self.cfg.get('max_pending_samples', 24))
        self.min_motion_clear_dwell = float(self.cfg.get('min_motion_clear_dwell_seconds', .28))
        self.model_path = root / 'data' / 'models' / 'safe_window_v532.joblib'
        self.legacy_model_paths = [
            root / 'data' / 'models' / 'safe_window_v531.joblib',
            root / 'data' / 'models' / 'safe_window_v530.joblib',
            root / 'data' / 'models' / 'safe_window_v529.joblib',
            root / 'data' / 'models' / 'safe_window_v528.joblib',
            root / 'data' / 'models' / 'safe_window_v527.joblib',
            root / 'data' / 'models' / 'safe_window_v526.joblib',
            root / 'data' / 'models' / 'safe_window_v525.joblib',
            root / 'data' / 'models' / 'safe_window_v524.joblib',
        ]
        self.failure_seed_path = root / 'data' / 'models' / 'v522_failure_seed.json'
        self.log_dir = root / 'data' / 'sessions'
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

        self.scaler = StandardScaler()
        self.model = SGDClassifier(
            loss='log_loss', alpha=float(self.cfg.get('sgd_alpha', 0.0015)),
            learning_rate='optimal', random_state=17
        )
        # V5.3.2: two-timescale learning. The persisted model is long-term
        # memory only; a fresh current-session learner adapts quickly to the
        # traffic regime of this game and is intentionally NOT persisted.
        self.session_scaler = StandardScaler()
        self.session_model = SGDClassifier(
            loss='log_loss',
            alpha=float(self.cfg.get('session_sgd_alpha', 0.0020)),
            learning_rate='constant',
            eta0=float(self.cfg.get('session_sgd_eta0', 0.020)),
            random_state=29
        )
        self.session_fitted = False
        self.session_n = 0
        self.session_safe_n = 0
        self.session_unsafe_n = 0
        self.session_min_samples = int(self.cfg.get('session_min_samples', 18))
        self.session_full_weight_samples = int(self.cfg.get('session_full_weight_samples', 90))
        self.last_heuristic_probability = 0.5
        self.last_longterm_probability = None
        self.last_session_probability = None
        self.fitted = False
        self.n = 0
        self.safe_n = 0
        self.unsafe_n = 0
        self.pending = deque(maxlen=self.max_pending)
        self.last_candidate = 0.0
        self.last_cycle_authorized = None
        self.last_save = time.time()
        self.save_interval = float(self.cfg.get('save_interval_seconds',300.0))
        self.save_during_run = bool(self.cfg.get('save_during_run',False))
        self.last_log_flush = 0.0
        self.session_started = time.time()

        # V5.2.3 sustained GREEN commitment.  The latest user run showed two
        # distinct signal populations: one-frame/flicker GREENs (~0.32 s median)
        # and sustained GREENs (~0.69 s median).  Both attributed failures were
        # from the transient class.  Do not expose the first qualifying frame;
        # require the safe state to persist, then allow only small soft-probability
        # dropouts while every hard hazard veto remains authoritative.
        self.green_commit_base = float(self.cfg.get('green_commit_dwell_seconds', .40))
        self.green_commit_hard_add = float(self.cfg.get('green_commit_hard_add_seconds', -.04))
        self.green_precommit_dropout_grace = float(self.cfg.get('green_precommit_dropout_grace_seconds', .14))
        self.green_precommit_exit_margin = float(self.cfg.get('green_precommit_exit_probability_margin', .025))
        self.green_commit_dropout_grace = float(self.cfg.get('green_commit_dropout_grace_seconds', .42))
        self.green_commit_exit_margin = float(self.cfg.get('green_commit_exit_probability_margin', .035))
        self.green_commit_exit_eta_margin = float(self.cfg.get('green_commit_exit_eta_margin_seconds', .06))
        # V5.2.9: minimum actionable display lease while hard safety remains clear.
        self.green_min_visible_hold = float(self.cfg.get('green_min_visible_hold_seconds', .65))
        # V5.3.7: a dynamic-gap state is already a physically verified busy->clear
        # transition. Do not consume the same opportunity again with a second
        # clear dwell + commit dwell. Admission still requires a useful action
        # lease; after admission the same verified cycle may continue until the
        # risk engine itself withdraws dynamic_gap_ready or a hard hazard appears.
        self.verified_gap_min_action_lease = float(
            self.cfg.get('verified_gap_min_action_lease_seconds', .42)
        )
        self.verified_gap_commit_seconds = float(
            self.cfg.get('verified_gap_commit_seconds', 0.0)
        )
        self._verified_active_cycle = None
        self.verified_gap_hold_max = float(
            self.cfg.get('verified_gap_hold_max_seconds', .75)
        )
        self._verified_hold_until = 0.0
        self._verified_hold_key = None
        self._commit_key = None
        self._commit_since = None
        self._commit_last_good = None
        self._commit_started = None
        self._commit_active = False

        # V5.3.9: strong LIVE verified gaps may override a stale/collapsed ML prior.
        self.verified_physical_override_enabled = bool(self.cfg.get('verified_gap_physical_override_enabled', True))
        self.verified_physical_min_heuristic = float(self.cfg.get('verified_gap_physical_min_heuristic_probability', .91))
        self.verified_physical_min_confidence = float(self.cfg.get('verified_gap_physical_min_confidence', .75))
        self.verified_physical_min_support = int(self.cfg.get('verified_gap_physical_min_support', 12))
        self.verified_physical_min_gap_p25 = float(self.cfg.get('verified_gap_physical_min_gap_p25_seconds', 1.80))
        self.verified_physical_min_action_lease = float(self.cfg.get('verified_gap_physical_min_action_lease_seconds', .32))
        self.verified_physical_max_raw = float(self.cfg.get('verified_gap_physical_max_raw_risk', 18.0))
        self.verified_physical_max_motion = float(self.cfg.get('verified_gap_physical_max_motion_ratio', .04))
        self.verified_physical_max_mog = float(self.cfg.get('verified_gap_physical_max_mog_ratio', .055))
        # V5.5.2 degraded-FPS presentation headroom. V5.5.1 admitted a GREEN
        # at ~2.34 FPS with 0.478 s action lease against a 0.467 s frame-margin
        # requirement: only ~11 ms of real headroom. Add a small reserve ONLY
        # when FPS is degraded; normal-FPS V5.5.1 behavior remains unchanged.
        self.degraded_lease_headroom = float(
            self.cfg.get('degraded_green_extra_lease_seconds', .08)
        )
        self.degraded_fps_threshold = float(
            self.cfg.get('degraded_green_fps_threshold', 2.8)
        )

        # V5.4.4 mode-aware verified-gap profiles. Hard traffic naturally has a
        # lower historical gap P25, so it is wrong to demand an easy-mode P25
        # before accepting a rare CURRENT large gap. Harder modes instead demand
        # more current confidence/lease and tighter instantaneous motion safety.
        self.mode_verified_profiles = {
            'EASY': {
                'standard_lease': float(self.cfg.get('mode_easy_standard_lease_seconds',.34)),
                'physical_lease': float(self.cfg.get('mode_easy_physical_lease_seconds',.18)),
                'heuristic': float(self.cfg.get('mode_easy_physical_min_heuristic',.90)),
                'confidence': float(self.cfg.get('mode_easy_physical_min_confidence',.64)),
                'support': int(self.cfg.get('mode_easy_physical_min_support',8)),
                'gap_p25': float(self.cfg.get('mode_easy_physical_min_gap_p25_seconds',1.75)),
                'raw': float(self.cfg.get('mode_easy_physical_max_raw_risk',18.0)),
                'motion': float(self.cfg.get('mode_easy_physical_max_motion_ratio',.040)),
                'mog': float(self.cfg.get('mode_easy_physical_max_mog_ratio',.055)),
            },
            'NORMAL': {
                'standard_lease': float(self.cfg.get('mode_normal_standard_lease_seconds',.42)),
                'physical_lease': float(self.cfg.get('mode_normal_physical_lease_seconds',.22)),
                'heuristic': float(self.cfg.get('mode_normal_physical_min_heuristic',.91)),
                'confidence': float(self.cfg.get('mode_normal_physical_min_confidence',.68)),
                'support': int(self.cfg.get('mode_normal_physical_min_support',9)),
                'gap_p25': float(self.cfg.get('mode_normal_physical_min_gap_p25_seconds',1.55)),
                'raw': float(self.cfg.get('mode_normal_physical_max_raw_risk',16.0)),
                'motion': float(self.cfg.get('mode_normal_physical_max_motion_ratio',.035)),
                'mog': float(self.cfg.get('mode_normal_physical_max_mog_ratio',.050)),
            },
            'HARD': {
                'standard_lease': float(self.cfg.get('mode_hard_standard_lease_seconds',.46)),
                'physical_lease': float(self.cfg.get('mode_hard_physical_lease_seconds',.26)),
                'heuristic': float(self.cfg.get('mode_hard_physical_min_heuristic',.93)),
                'confidence': float(self.cfg.get('mode_hard_physical_min_confidence',.72)),
                'support': int(self.cfg.get('mode_hard_physical_min_support',10)),
                'gap_p25': float(self.cfg.get('mode_hard_physical_min_gap_p25_seconds',1.30)),
                'raw': float(self.cfg.get('mode_hard_physical_max_raw_risk',14.0)),
                'motion': float(self.cfg.get('mode_hard_physical_max_motion_ratio',.030)),
                'mog': float(self.cfg.get('mode_hard_physical_max_mog_ratio',.045)),
            },
            'EXTREME': {
                'standard_lease': float(self.cfg.get('mode_extreme_standard_lease_seconds',.50)),
                'physical_lease': float(self.cfg.get('mode_extreme_physical_lease_seconds',.30)),
                'heuristic': float(self.cfg.get('mode_extreme_physical_min_heuristic',.94)),
                'confidence': float(self.cfg.get('mode_extreme_physical_min_confidence',.76)),
                'support': int(self.cfg.get('mode_extreme_physical_min_support',12)),
                'gap_p25': float(self.cfg.get('mode_extreme_physical_min_gap_p25_seconds',1.05)),
                'raw': float(self.cfg.get('mode_extreme_physical_max_raw_risk',12.0)),
                'motion': float(self.cfg.get('mode_extreme_physical_max_motion_ratio',.025)),
                'mog': float(self.cfg.get('mode_extreme_physical_max_mog_ratio',.040)),
            },
        }

        # V5.4.5 GO-NOW timing: V5.4.4 opened GREEN on the first clean
        # frame after a passing car. In the supplied run 37/45 GREEN starts
        # followed raw risk >=90 and 38/45 had <0.20 s confirmed clear time.
        # Hold WAIT until the tail of the pass has actually cleared. Harder
        # modes use a longer settle. If a target-lane track is still alive,
        # add a small extra tail-clear allowance.
        self.mode_post_pass_settle = {
            'EASY': float(self.cfg.get('mode_easy_post_pass_settle_seconds', .18)),
            'NORMAL': float(self.cfg.get('mode_normal_post_pass_settle_seconds', .24)),
            'HARD': float(self.cfg.get('mode_hard_post_pass_settle_seconds', .30)),
            'EXTREME': float(self.cfg.get('mode_extreme_post_pass_settle_seconds', .34)),
        }
        # V5.5.1: a motion-clear clock can start while the tail of a visible
        # vehicle is still leaving the crossing. The V5.5.0 failure opened
        # GREEN only ~0.27 s after a high-risk/visible threat and the next car
        # returned ~0.26 s later, despite a predicted 2.19 s gap. Require a
        # short independent time since the last direct threat before starting
        # a new verified-gap GREEN.
        self.threat_tail_guard_enabled = bool(
            self.cfg.get('threat_tail_guard_enabled', True)
        )
        self.mode_threat_tail_settle = {
            'EASY': float(self.cfg.get('mode_easy_threat_tail_settle_seconds', .55)),
            'NORMAL': float(self.cfg.get('mode_normal_threat_tail_settle_seconds', .55)),
            'HARD': float(self.cfg.get('mode_hard_threat_tail_settle_seconds', .55)),
            'EXTREME': float(self.cfg.get('mode_extreme_threat_tail_settle_seconds', .55)),
        }
        self.mode_track_tail_add = {
            'EASY': float(self.cfg.get('mode_easy_track_tail_add_seconds', .10)),
            'NORMAL': float(self.cfg.get('mode_normal_track_tail_add_seconds', .10)),
            'HARD': float(self.cfg.get('mode_hard_track_tail_add_seconds', .12)),
            'EXTREME': float(self.cfg.get('mode_extreme_track_tail_add_seconds', .14)),
        }

        # V5.4.0: mature sustained observed-clear traffic evidence is allowed to
        # replace the obsolete universal 1.58 s forecast floor. The V5.3.6 floor
        # was introduced from failure labels that later proved mostly false
        # attribution. This path is deliberately strict on live gap history,
        # motion/MOG, raw risk and heuristic confidence.
        self.sustained_observed_enabled = bool(
            self.cfg.get('sustained_observed_clear_enabled', True)
        )
        self.sustained_observed_min_eta = float(
            self.cfg.get('sustained_observed_clear_min_eta_seconds', 1.62)
        )
        self.sustained_observed_min_elapsed = float(
            self.cfg.get('sustained_observed_clear_min_elapsed_seconds', 1.10)
        )
        self.sustained_observed_min_gap_p25 = float(
            self.cfg.get('sustained_observed_clear_min_gap_p25_seconds', 1.75)
        )
        self.sustained_observed_min_support = int(
            self.cfg.get('sustained_observed_clear_min_support', 36)
        )
        self.sustained_observed_min_heuristic = float(
            self.cfg.get('sustained_observed_clear_min_heuristic_probability', .92)
        )
        self.sustained_observed_max_raw = float(
            self.cfg.get('sustained_observed_clear_max_raw_risk', 12.0)
        )
        self.sustained_observed_max_motion = float(
            self.cfg.get('sustained_observed_clear_max_motion_ratio', .025)
        )
        self.sustained_observed_max_mog = float(
            self.cfg.get('sustained_observed_clear_max_mog_ratio', .035)
        )
        # A committed GREEN may survive a provenance/forecast-policy flip for a
        # short display lease, but never a real physical hard veto.
        self.active_green_hold_min_eta = float(
            self.cfg.get('active_green_hold_min_eta_seconds', 1.20)
        )
        # V5.4.2: cancel an already-visible GREEN at the first strong
        # live-motion rise instead of waiting for the broader generic hard veto.
        self.active_green_motion_rise_raw = float(
            self.cfg.get('active_green_motion_rise_raw_risk', 30.0)
        )
        self.active_green_motion_rise_ratio = float(
            self.cfg.get('active_green_motion_rise_ratio', .06)
        )
        self.active_green_motion_rise_mog = float(
            self.cfg.get('active_green_motion_rise_mog_ratio', .08)
        )

        # V5.2.3 direct acted-GREEN feedback. Earlier V5 builds could log a
        # GREEN failure but skip it from supervised learning when chicken
        # movement was first detected after GREEN disappeared. Keep an
        # explicit short-term memory of the exact V5 state that failed so a
        # near-identical state is penalized immediately rather than waiting
        # for thousands of generic retrospective labels to move SGD weights.
        self.failure_feedback = deque(maxlen=int(self.cfg.get('failure_memory_max', 80)))
        self.feedback_failures = 0
        self.feedback_successes = 0
        self.failure_memory_half_life = float(self.cfg.get('failure_memory_half_life_seconds', 1800.0))
        self.failure_memory_sigma = float(self.cfg.get('failure_memory_sigma', .16))
        self.failure_memory_hard_similarity = float(self.cfg.get('failure_memory_hard_similarity', .99))
        self.failure_memory_prob_penalty = float(self.cfg.get('failure_memory_probability_penalty', .04))

        self.log_path = self.log_dir / time.strftime('safe_window_v5518_%Y%m%d_%H%M%S.csv')
        self._log_file = self.log_path.open('w', newline='', encoding='utf-8')
        self._writer = csv.writer(self._log_file)
        self._writer.writerow([
            'ts','probability','threshold','decision','hard_ok','hard_reason',
            'v4_green','v4_reason','eta','stage_difficulty','cycle_id',
            'train_n','safe_n','unsafe_n','label_event','failure_similarity','feedback_failures','feedback_successes',
            'raw_decision','commit_elapsed','commit_required','committed','commit_age',
            'gap_provenance','required_eta','historical_slow_after_risk',
            'admission_threshold','effective_difficulty','physical_override','observed_clear_override','verified_physical_override',
            'heuristic_probability','longterm_probability','session_probability',
            'session_train_n','session_safe_n','session_unsafe_n',
            'verified_gap_fastpath','verified_gap_action_lease','verified_gap_min_action_lease',
            'verified_gap_physical_min_action_lease','verified_gap_lease_tier',
            'verified_gap_selected_lease_required','difficulty_mode',
            'difficulty_mode_score','difficulty_mode_switches',
            'verified_gap_held','verified_gap_hold_remaining',
            'sustained_observed_override','active_green_hold_override',
            'policy_eta','observed_clear_guard_eta','session_speed_guard_reference',
            'session_speed_support','post_pass_settle_required',
            'post_pass_clear_elapsed','post_pass_ready',
            'recent_threat_age','threat_tail_settle_required','threat_tail_ready'
        ])
        self._log_file.flush()
        self._load()
        self._load_failure_seed()

    @staticmethod
    def _f(v, default=0.0):
        try:
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return float(default)
            return float(v)
        except Exception:
            return float(default)

    def _features(self, s: dict):
        eta = min(3.0, self._f(s.get('effective_eta'), 0.0)) / 2.2
        clear_dwell = min(3.0, self._f(s.get('clear_dwell'), 0.0)) / 2.0
        motion_dwell = min(3.0, self._f(s.get('motion_clear_dwell'), 0.0)) / 1.5
        motion_ratio = self._f(s.get('motion_corridor_ratio'), 1.0)
        motion_clear = max(0.0, 1.0 - min(1.0, motion_ratio / .12))
        vis = self._f(s.get('lane_visibility_score'), 0.0)
        raw_inv = max(0.0, 1.0 - self._f(s.get('raw_risk', s.get('risk', 50.0))) / 100.0)
        src = self._f(s.get('eta_source_reliability'), .5)
        adaptive = self._f(s.get('adaptive_confidence'), .5)
        gap = min(3.0, self._f(s.get('motion_gap_p25'), 0.0)) / 1.8
        dg = self._f(s.get('dynamic_gap_confidence'), 0.0)
        difficulty = np.clip(self._f(s.get('stage_difficulty_score'), .5), 0.0, 1.0)
        recent_rel = self._f(s.get('recent_green_reliability'), .5)
        crash_safe = max(0.0, 1.0 - self._f(s.get('crash_memory_score'), 0.0))
        mode=str(s.get('slow_window_mode',''))
        slow_before = 1.0 if mode in ('slow-before','live-slow-before') else 0.0
        slow_after = 1.0 if mode in ('slow-after','confirmed-slow-after') or bool(s.get('slow_after_guard_active',False)) else 0.0
        follower_eta = self._f(s.get('slow_window_follower_eta'), 0.0)
        follower_clear = min(1.0, max(0.0,follower_eta) / 2.0)
        slow_support=self._f(s.get('slow_window_profile_support'),0.0)
        slow_conf=self._f(s.get('slow_window_profile_confidence'),0.0)
        slow_p25=self._f(s.get('slow_window_p25_gap'),0.0)
        slow_after_profile=min(1.0,slow_support/12.0)*min(1.0,slow_conf)*min(1.0,slow_p25/1.8)
        proc = 1.0 if bool(s.get('processing_healthy', True)) else 0.0
        return np.asarray([
            eta, clear_dwell, motion_dwell, motion_clear, vis, raw_inv,
            src, adaptive, gap, dg, 1.0-difficulty, recent_rel,
            crash_safe, slow_before, slow_after, follower_clear,
            slow_after_profile, proc
        ], dtype=np.float64)

    def _slow_before_verified(self, s: dict):
        mode=str(s.get('slow_window_mode',''))
        if mode not in ('slow-before','live-slow-before'):
            return False
        eta=self._f(s.get('slow_window_eta'),0.0)
        req=self._f(s.get('slow_window_required_eta'),1.0)
        follower=s.get('slow_window_follower_eta')
        follower_ok=True if follower in (None,'') else self._f(follower,0.0) >= max(1.20,req)
        return bool(eta >= req + .06 and follower_ok)

    def _slow_after_verified(self, s: dict):
        mode=str(s.get('slow_window_mode',''))
        if mode not in ('slow-after','confirmed-slow-after'):
            return False
        support=int(self._f(s.get('slow_window_profile_support'),0.0))
        conf=self._f(s.get('slow_window_profile_confidence'),0.0)
        p25=self._f(s.get('slow_window_p25_gap'),0.0)
        pfast=self._f(s.get('slow_window_p_fast'),1.0)
        follower=s.get('slow_window_follower_eta')
        follower_eta=(0.0 if follower in (None,'') else self._f(follower,0.0))
        return bool(support >= 8 and conf >= .74 and p25 >= 1.45 and pfast <= .28 and follower_eta >= 1.45)

    def _strong_motion_gap_verified(self, s: dict):
        """Independent busy->clear proof from the target-lane motion ROI.

        V5.3.3 already allowed a strong motion-gap history to substitute for
        sparse CZN event counts in the physical override, but _live_gap_verified
        rejected the state first whenever czn_live_ready was false. That made
        the override unreachable during bootstrap. Keep this path deliberately
        strict: mature support, a strong lower-tail gap, and a currently clean
        corridor/MOG are all required.
        """
        return bool(
            bool(s.get('motion_live_ready', False))
            and bool(s.get('dynamic_gap_preceding_busy_ok', False))
            and self._f(s.get('motion_preceding_busy_duration'), 0.0) >= self.min_preceding_busy
            and int(self._f(s.get('motion_gap_support'), 0.0)) >= self.observed_physical_strong_gap_support
            and self._f(s.get('motion_gap_p25'), 0.0) >= self.observed_physical_strong_gap_p25
            and self._f(s.get('motion_corridor_ratio'), 1.0) <= self.observed_physical_max_motion
            and self._f(s.get('dynamic_gap_mog_global_ratio'), 1.0) <= self.observed_physical_max_mog
        )

    def _live_gap_verified(self, s: dict):
        """Require current, observable gap provenance before GREEN.

        V5.2 could issue high-probability GREEN while dynamic/gap sources were
        not ready and the target ROI contained no tracks.  A learned SAFE prior
        is useful, but it is not proof that the *current* gap exists.
        """
        # Keep legacy/unit-test callers working when none of the live-gap
        # telemetry exists. Production state always supplies these keys.
        keys = (
            'active_tracks','dynamic_gap_ready','gap_open_ready',
            'motion_live_ready','czn_live_ready','dynamic_gap_preceding_busy_ok',
            'motion_gap_support','motion_gap_p25','motion_preceding_busy_duration'
        )
        if not any(k in s for k in keys):
            return True

        if self._slow_before_verified(s):
            return True
        if bool(s.get('dynamic_gap_ready', False)) or bool(s.get('gap_open_ready', False)):
            return True

        # A live tracked object can itself provide current geometry, provided it
        # is not already a visible/uncertain threat (those are vetoed below).
        if int(self._f(s.get('active_tracks'), 0.0)) > 0:
            return True

        # For an apparently empty lane, require evidence that we actually saw a
        # busy->clear transition in this target ROI.  This distinguishes a real
        # observed gap from a blind/empty ROI.
        motion_gap_ok = bool(
            bool(s.get('motion_live_ready', False))
            and bool(s.get('dynamic_gap_preceding_busy_ok', False))
            and self._f(s.get('motion_preceding_busy_duration'), 0.0) >= self.min_preceding_busy
            and int(self._f(s.get('motion_gap_support'), 0.0)) >= self.min_live_gap_support
            and self._f(s.get('motion_gap_p25'), 0.0) >= self.min_live_gap_p25
        )
        if not motion_gap_ok:
            return False
        if bool(s.get('czn_live_ready', False)):
            return True
        # Strong independent raw-motion evidence is allowed to bootstrap the
        # gap verifier before tracker/CZN crossing events mature.
        return self._strong_motion_gap_verified(s)

    def _gap_provenance(self, s: dict):
        live_keys=(
            'active_tracks','dynamic_gap_ready','gap_open_ready','motion_live_ready',
            'czn_live_ready','motion_gap_support','motion_current_clear_elapsed'
        )
        if not any(k in s for k in live_keys):
            return 'legacy'
        if self._slow_before_verified(s):
            return 'slow-before'
        if bool(s.get('dynamic_gap_ready',False)) or bool(s.get('gap_open_ready',False)):
            return 'verified-gap'
        if int(self._f(s.get('active_tracks'),0.0)) > 0:
            return 'tracked-forecast'
        if self._live_gap_verified(s):
            return 'observed-clear'
        return 'unverified'

    def _historical_slow_after_risk(self, s: dict):
        """Soft risk from learned post-slow headways, separate from recent hard guard."""
        reason=str(s.get('slow_window_reason','') or '')
        support=int(self._f(s.get('slow_window_profile_support'),0.0))
        conf=float(np.clip(self._f(s.get('slow_window_profile_confidence'),0.0),0.0,1.0))
        p25=self._f(s.get('slow_window_p25_gap'),0.0)
        if not reason.startswith('SLOW AFTER GAP') or support < 8 or p25 <= 0.0:
            return 0.0
        deficit=max(0.0,self.historical_slow_after_safe_gap-p25)
        return float(np.clip((deficit/max(.20,self.historical_slow_after_safe_gap*.45))*conf,0.0,1.0))

    def _required_eta_for_green(self, s: dict, provenance: str, slow_hist_risk: float):
        if provenance in ('verified-gap','slow-before','legacy'):
            req=max(self.absolute_eta,self.verified_gap_min_eta)
        elif provenance == 'observed-clear':
            # A genuinely empty target ROI is judged mainly from current gap
            # maturity/history below; do not recreate the old global ETA wall.
            req=max(self.absolute_eta,self.observed_clear_min_eta)
        else:
            req=max(self.absolute_eta,self.forecast_min_eta)
            req += self.forecast_slow_after_eta_penalty*float(np.clip(slow_hist_risk,0.0,1.0))
        return float(req)

    def _observed_clear_physical_ready(self, s: dict, required_eta: float, prob: float):
        if not self.observed_physical_override_enabled:
            return False
        if self._effective_difficulty(s) < self.observed_physical_min_difficulty:
            return False
        current_clear=self._f(s.get('motion_current_clear_elapsed'),0.0)
        gap_p25=self._f(s.get('motion_gap_p25'),0.0)
        gap_support=int(self._f(s.get('motion_gap_support'),0.0))
        czn_events=int(self._f(s.get('czn_confirmed_events'),0.0))
        if current_clear < self.observed_physical_min_elapsed:
            return False
        if gap_p25 < self.observed_physical_min_gap_p25:
            return False
        strong_gap_telemetry_present = any(k in s for k in (
            'motion_live_ready','dynamic_gap_preceding_busy_ok',
            'motion_preceding_busy_duration'
        ))
        strong_gap = bool(
            gap_support >= self.observed_physical_strong_gap_support
            and gap_p25 >= self.observed_physical_strong_gap_p25
            and (
                not strong_gap_telemetry_present
                or self._strong_motion_gap_verified(s)
            )
        )
        current_czn = bool(czn_events >= self.observed_physical_min_czn_events)
        # Legacy/unit-test callers from older builds may not supply the new CZN
        # event counter. Production V5.3.x state always does. Preserve backward
        # compatibility only when that telemetry key is genuinely absent.
        evidence_telemetry_present = ('czn_confirmed_events' in s)
        if evidence_telemetry_present and not (current_czn or strong_gap):
            return False
        if self._f(s.get('effective_eta'),0.0) < float(required_eta) + self.observed_physical_eta_margin:
            return False
        if self._f(s.get('motion_corridor_ratio'),1.0) > self.observed_physical_max_motion:
            return False
        if self._f(s.get('dynamic_gap_mog_global_ratio'),1.0) > self.observed_physical_max_mog:
            return False
        if self._f(s.get('raw_risk',s.get('risk',50.0))) > self.observed_physical_max_raw:
            return False
        if float(prob) < self.observed_physical_min_probability:
            return False
        return True

    def _observed_clear_policy_eta(self, s: dict):
        """Conservative ETA for untracked/observed-clear permissions.

        Clear-zone ETA may be based on the current 180 s speed window. V5.4.0
        showed that after a long quiet stretch this could fall back to ~392 px/s
        even though the same game had already produced 700+ px/s cars. Scale ETA
        by the current-session fast-speed guard when available. Verified dynamic
        gaps do not use this helper because their remaining time is measured from
        the actual busy->clear transition.
        """
        eta=self._f(s.get('effective_eta'),0.0)
        base=self._f(s.get('czn_speed_reference'),0.0)
        guard=self._f(s.get('czn_observed_clear_speed_reference'),0.0)
        if eta <= 0.0 or base <= 0.0 or guard <= base:
            return float(eta)
        return float(max(0.0,eta*base/max(base,guard)))

    def _sustained_observed_clear_ready(self, s: dict, heuristic_prob: float):
        """Strict live physical proof for a mature observed-clear opportunity."""
        if not self.sustained_observed_enabled:
            return False
        # Hard/Extreme traffic uses current verified busy->clear gaps only. The
        # old observed-clear shortcut caused a genuine crash when traffic changed
        # faster than the tracker. EASY/NORMAL may still use the strict guarded
        # observed-clear path.
        if self._difficulty_mode(s) not in ('EASY','NORMAL'):
            return False
        if self._observed_clear_policy_eta(s) < self.sustained_observed_min_eta:
            return False
        if self._f(s.get('motion_current_clear_elapsed'),0.0) < self.sustained_observed_min_elapsed:
            return False
        if int(self._f(s.get('motion_gap_support'),0.0)) < self.sustained_observed_min_support:
            return False
        if self._f(s.get('motion_gap_p25'),0.0) < self.sustained_observed_min_gap_p25:
            return False
        if float(heuristic_prob) < self.sustained_observed_min_heuristic:
            return False
        if self._f(s.get('raw_risk',s.get('risk',50.0))) > self.sustained_observed_max_raw:
            return False
        if self._f(s.get('motion_corridor_ratio'),1.0) > self.sustained_observed_max_motion:
            return False
        if self._f(s.get('dynamic_gap_mog_global_ratio'),1.0) > self.sustained_observed_max_mog:
            return False
        return True

    def _difficulty_mode(self, s: dict):
        m=str(s.get('difficulty_mode','NORMAL') or 'NORMAL').upper()
        return m if m in self.mode_verified_profiles else 'NORMAL'

    def _mode_verified_profile(self, s: dict):
        return self.mode_verified_profiles[self._difficulty_mode(s)]

    def _threat_tail_settle_requirement(self, s: dict):
        return float(self.mode_threat_tail_settle.get(
            self._difficulty_mode(s), .55
        ))

    def _threat_tail_ready(self, s: dict):
        if not self.threat_tail_guard_enabled:
            return True
        age=self._f(s.get('recent_threat_age'),1e9)
        return bool(age >= self._threat_tail_settle_requirement(s))

    def _post_pass_settle_requirement(self, s: dict):
        mode=self._difficulty_mode(s)
        req=float(self.mode_post_pass_settle.get(mode,.24))
        if int(self._f(s.get('active_tracks'),0.0)) > 0:
            req += float(self.mode_track_tail_add.get(mode,.10))
        return float(req)

    def _post_pass_clear_elapsed(self, s: dict):
        # Prefer the raw motion clear clock because it resets immediately when
        # target-lane motion returns. Do not max() several clocks: a stale older
        # dwell must never hide a newly reset current-clear clock.
        for key in ('motion_current_clear_elapsed','motion_clear_dwell','dynamic_gap_effective_clear_elapsed'):
            if key in s and s.get(key) not in (None,''):
                return float(self._f(s.get(key),0.0))
        return 0.0

    def _degraded_frame_margin(self, s: dict):
        fps=max(2.0,self._f(s.get('processing_fps'),6.0))
        frame_margin=(1.0/fps)+.04
        degraded=bool(
            bool(s.get('processing_degraded',False))
            or fps < self.degraded_fps_threshold
        )
        headroom=self.degraded_lease_headroom if degraded else 0.0
        return float(frame_margin+headroom), float(headroom)

    def _verified_gap_lease_requirement(self, s: dict):
        # At low FPS, require at least one frame of extra start-time margin so
        # a GREEN cannot be born already expired. The dynamic-gap required ETA
        # already includes reaction/pipeline budgets; this is only an extra
        # presentation/actionability reserve.
        frame_margin,_headroom=self._degraded_frame_margin(s)
        engine_floor=self._f(s.get('dynamic_gap_lease_required'),0.0)
        prof=self._mode_verified_profile(s)
        return float(max(
            float(prof['standard_lease']), frame_margin, engine_floor
        ))

    def _verified_gap_physical_lease_requirement(self, s: dict):
        """Smaller reserve for exceptionally strong live verified gaps.

        RiskEngine's dynamic_gap_required_eta already includes jump time, safety,
        learned reaction delay and measured pipeline latency. V5.4.2 then added
        another flat 0.55 s and rejected most otherwise-safe verified cycles.
        Strong physical evidence needs only an FPS/presentation reserve on top
        of the already-complete required ETA.
        """
        frame_margin,_headroom=self._degraded_frame_margin(s)
        engine_floor=self._f(s.get('dynamic_gap_lease_required'),0.0)
        prof=self._mode_verified_profile(s)
        return float(max(
            float(prof['physical_lease']), frame_margin, engine_floor
        ))

    def _verified_gap_physical_ready(self, s: dict, heuristic_prob: float):
        """Strong current busy->clear evidence after all hard vetoes pass.

        This can override only the learned probability. It cannot override any
        hard vehicle, target, viewport, processing, slow, MOG/motion, crash-memory,
        ETA or action-lease veto.
        """
        if not self.verified_physical_override_enabled:
            return False
        if not bool(s.get('dynamic_gap_ready', False)):
            return False
        if not bool(s.get('dynamic_gap_preceding_busy_ok', False)):
            return False
        prof=self._mode_verified_profile(s)
        if float(heuristic_prob) < float(prof['heuristic']):
            return False
        if self._f(s.get('dynamic_gap_confidence'), 0.0) < float(prof['confidence']):
            return False
        if int(self._f(s.get('motion_gap_support'), 0.0)) < int(prof['support']):
            return False
        if self._f(s.get('motion_gap_p25'), 0.0) < float(prof['gap_p25']):
            return False
        lease_req=self._verified_gap_physical_lease_requirement(s)
        if self._f(s.get('dynamic_gap_action_lease'), 0.0) < lease_req:
            return False
        if self._f(s.get('raw_risk', s.get('risk', 50.0))) > float(prof['raw']):
            return False
        if self._f(s.get('motion_corridor_ratio'), 1.0) > float(prof['motion']):
            return False
        if self._f(s.get('dynamic_gap_mog_global_ratio'), 1.0) > float(prof['mog']):
            return False
        return True

    def _hard_veto(self, s: dict):
        if not bool(s.get('processing_healthy', True)):
            return False, 'PROCESSING'
        # V5.2: zero tracks is not itself a tracking failure. V5.1 repeatedly
        # reset perfectly empty lanes. Only geometric target/proposal desync is
        # authoritative.
        if bool(s.get('sensor_desync', False)):
            return False, 'TARGET DESYNC'
        if bool(s.get('tracking_rewarm', False)):
            return False, 'TRACK REWARM'
        if bool(s.get('viewport_hold', False)) or bool(s.get('vision_hold', False)):
            return False, 'VISION/VIEWPORT'
        if not bool(s.get('target_green_geometry_ok', False)):
            return False, 'TARGET'
        if not bool(s.get('motion_ready', False)):
            return False, 'MOTION REWARM'
        if ('crossing_motion_available' in s and
                (not s['crossing_motion_available'] or not s.get('crossing_motion_clear', False))):
            return False, s.get('crossing_motion_reason') or 'CROSSING OCCUPIED'

        # V5.4.2: once GREEN is visible, a sharp rise in raw/motion evidence is
        # an early incoming-vehicle warning. Cancel before the broader generic
        # thresholds are reached. This never creates GREEN; it can only end one.
        if self._commit_active:
            if self._f(s.get('raw_risk',s.get('risk',50.0))) > self.active_green_motion_rise_raw:
                return False, 'GREEN MOTION RISE'
            if self._f(s.get('motion_corridor_ratio'),1.0) > self.active_green_motion_rise_ratio:
                return False, 'GREEN MOTION RISE'
            if self._f(s.get('dynamic_gap_mog_global_ratio'),0.0) > self.active_green_motion_rise_mog:
                return False, 'GREEN MOTION RISE'

        slow_before=self._slow_before_verified(s)
        slow_after_guard=bool(s.get('slow_after_guard_active',False))
        slow_after_ok=self._slow_after_verified(s)

        if not self._live_gap_verified(s):
            return False, 'LIVE GAP UNVERIFIED'

        dynamic_verified = bool(s.get('dynamic_gap_ready', False))

        # V5.4.5: a verified gap is not yet an instruction to GO on the very
        # first clear-looking frame after a car. Wait for a short mode-specific
        # post-pass settle so GREEN means "click now", not "the gap just
        # started forming". This also cancels an active GREEN if the clear
        # clock resets because another car/motion enters.
        if dynamic_verified and not slow_before:
            # Independent convoy-tail guard. Do not treat a tiny transparent
            # interval between adjacent vehicles as a full traffic gap merely
            # because motion dropped for a frame or two.
            if not self._threat_tail_ready(s):
                return False, 'THREAT TAIL SETTLE'
            settle_req=self._post_pass_settle_requirement(s)
            clear_elapsed=self._post_pass_clear_elapsed(s)
            if clear_elapsed < settle_req:
                return False, 'POST PASS SETTLE'

        # V5.4.3: lease admission is evaluated after the current frame's strong
        # physical classification is known. RiskEngine already enforces its own
        # minimum lease before dynamic_gap_ready can become true.

        # Asymmetric slow logic from observed play: a verified approaching slow
        # car can create a usable BEFORE window, but immediately AFTER a slow car
        # is treated as risky unless the follower/headway profile is strongly
        # verified.
        if slow_after_guard and not slow_after_ok:
            return False, 'AFTER SLOW GUARD'
        if bool(s.get('visible_threat', False)) and not slow_before:
            return False, 'VISIBLE THREAT'
        if int(s.get('uncertain_incoming_count', 0)) > 0:
            return False, 'UNCERTAIN VEHICLE'
        if not bool(s.get('lane_visibility_ok', False)) and self._f(s.get('lane_visibility_score')) < self.min_visibility:
            return False, 'VISIBILITY'
        if self._f(s.get('motion_corridor_ratio'), 1.0) > self.max_motion_ratio and not slow_before:
            return False, 'MOTION BUSY'
        if (
            self._f(s.get('motion_clear_dwell'), 0.0) < self.min_motion_clear_dwell
            and not slow_before
            and not dynamic_verified
        ):
            return False, 'CLEAR LEASE'
        if self._f(s.get('dynamic_gap_mog_global_ratio'), 0.0) > self.max_mog and not slow_before:
            return False, 'MOG BUSY'
        if self._f(s.get('raw_risk', s.get('risk', 50.0))) > self.max_raw_risk and not slow_before:
            return False, 'RAW RISK'
        if self._f(s.get('effective_eta'), 0.0) < self.absolute_eta:
            return False, 'PHYSICAL ETA'
        if self._f(s.get('crash_memory_score'), 0.0) >= .90 and int(s.get('crash_memory_matches',0)) >= 2:
            return False, 'REPEATED CRASH'
        if int(s.get('dynamic_gap_slow_guard',0)) and not slow_before and not slow_after_ok:
            return False, 'SLOW APPROACH'
        return True, ''

    def _effective_difficulty(self, s: dict):
        """Current-session difficulty for admission/commit tuning.

        Hardcore play is often compressed headways plus speed. Earlier builds
        could call that regime easy because the stage score lagged. Use only
        live-session evidence so a fresh game does not inherit old difficulty.
        """
        stage = np.clip(self._f(s.get('stage_difficulty_score'), .5), 0.0, 1.0)
        speed = np.clip(self._f(s.get('live_speed_difficulty_score'), 0.0), 0.0, 1.0)
        density = np.clip(self._f(s.get('live_density_difficulty_score'), 0.0), 0.0, 1.0)
        support = int(self._f(s.get('motion_gap_support'), 0.0))
        if support >= self.min_live_gap_support and bool(s.get('processing_healthy', True)):
            gap_raw = s.get('stage_gap_p25')
            if gap_raw is None or self._f(gap_raw,0.0) <= 0.0:
                gap_raw = s.get('motion_gap_p25')
            gap_d = 0.0
            if gap_raw is not None and self._f(gap_raw,0.0) > 0.0:
                gap_p25 = self._f(gap_raw, 1.25)
                den = max(.10, self.gap_difficulty_easy_seconds-self.gap_difficulty_hard_seconds)
                gap_d = np.clip((self.gap_difficulty_easy_seconds-gap_p25)/den, 0.0, 1.0)
            stage = max(
                float(stage),
                self.speed_difficulty_weight*float(speed),
                self.gap_difficulty_weight*float(gap_d),
                self.density_difficulty_weight*float(density),
            )
        return float(np.clip(stage, 0.0, 1.0))

    def _physical_probability_floor(self, provenance: str, difficulty: float, slow_hist_risk: float):
        """Confidence floor after all non-negotiable physical vetoes pass."""
        d=float(np.clip(difficulty,0.0,1.0))
        def lerp(easy,hard):
            return float(easy + d*(hard-easy))
        if provenance == 'verified-gap':
            floor=lerp(self.verified_prob_easy,self.verified_prob_hard)
        elif provenance == 'observed-clear':
            floor=lerp(self.observed_prob_easy,self.observed_prob_hard)
        elif provenance == 'slow-before':
            floor=lerp(self.slow_before_prob_easy,self.slow_before_prob_hard)
        elif provenance == 'tracked-forecast':
            floor=lerp(self.tracked_prob_easy,self.tracked_prob_hard)
        else:
            return None
        floor += self.physical_slow_risk_prob_penalty*float(np.clip(slow_hist_risk,0.0,1.0))
        return float(np.clip(floor,.68,.93))

    def _threshold(self, s: dict):
        d = self._effective_difficulty(s)
        # Keep the existing easy->hard confidence concept, but V5.2.4's final
        # max(..., .90) clamp accidentally disabled the configured hard-game
        # threshold.  V5.2.5 honors a bounded floor of 0.885; all physical and
        # learned-failure vetoes remain authoritative.
        if d <= .30:
            t = self.easy_threshold
        elif d >= .72:
            t = self.hard_threshold
        else:
            f = (d-.30)/.42
            t = self.easy_threshold + f*(self.hard_threshold-self.easy_threshold)
        rel = self._f(s.get('recent_green_reliability'), .5)
        if int(s.get('recent_green_failures',0)) >= 1:
            t += min(.05, .08*(.65-rel)) if rel < .65 else 0.0
        if int(s.get('recent_green_successes',0)) >= 2 and rel > .72:
            t -= min(.025, .04*(rel-.72))
        floor = float(self.cfg.get('adaptive_probability_floor', .885))
        return float(np.clip(max(t, floor), floor, .93))

    def _heuristic_probability(self, s: dict, x: np.ndarray):
        # Deliberately smooth: unlike V4 it does not turn each individual soft
        # heuristic into another hard blocker.
        score = (
            .22*x[0] + .09*x[1] + .09*x[2] + .15*x[3] + .08*x[4]
            + .08*x[5] + .06*x[6] + .05*x[7] + .06*x[8] + .04*x[9]
            + .03*x[10] + .02*x[11] + .02*x[12] + .06*x[13]
            - .09*x[14] + .03*x[15] + .04*x[16] + .01*x[17]
        )
        # Convert a roughly [0,1.3] evidence score to a probability with a
        # forgiving centre; hard vetoes provide the non-negotiable safety.
        return float(1.0/(1.0+math.exp(-6.0*(score-.48))))

    def _predict(self, s: dict, x: np.ndarray):
        h = self._heuristic_probability(s, x)
        self.last_heuristic_probability=float(h)
        self.last_longterm_probability=None
        self.last_session_probability=None
        if not self.fitted or self.n < self.min_samples:
            return h, 'bootstrap'
        try:
            z = self.scaler.transform([x])
            p_long = float(self.model.predict_proba(z)[0,1])
            self.last_longterm_probability=float(p_long)
        except Exception:
            return h, 'bootstrap'
        if not self.session_fitted or self.session_n < self.session_min_samples:
            return float(.60*h + .40*p_long), 'longterm-prior'
        try:
            zs=self.session_scaler.transform([x])
            p_session=float(self.session_model.predict_proba(zs)[0,1])
            self.last_session_probability=float(p_session)
            span=max(1,self.session_full_weight_samples-self.session_min_samples)
            a=float(np.clip((self.session_n-self.session_min_samples)/span,0.0,1.0))
            w_session=.25+.35*a
            w_long=.25-.10*a
            w_heur=1.0-w_session-w_long
            return float(w_heur*h + w_long*p_long + w_session*p_session), 'session-adaptive'
        except Exception:
            return float(.60*h + .40*p_long), 'longterm-prior'

    def _unsafe_observed(self, s: dict):
        slow_before=self._slow_before_verified(s)
        return bool(
            (s.get('visible_threat',False) and not slow_before)
            or int(s.get('uncertain_incoming_count',0)) > 0
            or (self._f(s.get('motion_corridor_ratio'),1.0) > self.max_motion_ratio and not slow_before)
            or (self._f(s.get('raw_risk',s.get('risk',50))) > 58.0 and not slow_before)
            or (self._f(s.get('dynamic_gap_mog_global_ratio'),0.0) > .16 and not slow_before)
            or (bool(s.get('slow_after_guard_active',False)) and not self._slow_after_verified(s))
            or bool(s.get('crash_event', False))
        )

    def _train_one(self, x, y, weight=1.0):
        x = np.asarray(x, dtype=np.float64)
        if x.shape[0] != len(self.FEATURE_NAMES) or not np.all(np.isfinite(x)):
            return 0
        self.scaler.partial_fit([x])
        z = self.scaler.transform([x])
        sw=np.asarray([max(.05,float(weight))],dtype=float)
        if not self.fitted:
            self.model.partial_fit(
                z, [int(y)], classes=np.asarray([0,1]), sample_weight=sw
            )
            self.fitted = True
        else:
            self.model.partial_fit(z, [int(y)], sample_weight=sw)
        self.n += 1
        if y:
            self.safe_n += 1
        else:
            self.unsafe_n += 1
        try:
            self.session_scaler.partial_fit([x])
            zs=self.session_scaler.transform([x])
            if not self.session_fitted:
                self.session_model.partial_fit(
                    zs,[int(y)],classes=np.asarray([0,1]),sample_weight=sw
                )
                self.session_fitted=True
            else:
                self.session_model.partial_fit(zs,[int(y)],sample_weight=sw)
            self.session_n += 1
            if y:
                self.session_safe_n += 1
            else:
                self.session_unsafe_n += 1
        except Exception:
            pass
        return 1

    def _failure_similarity(self, x, now=None):
        if not self.failure_feedback:
            return 0.0
        now=time.time() if now is None else float(now)
        x=np.asarray(x,dtype=np.float64)
        # Emphasise geometry/gap/slow/follower features. The inputs are already
        # normalized to roughly 0..1, so a weighted Euclidean distance is
        # stable across sessions without depending on the current scaler.
        w=np.asarray([
            1.5, .5, .7, 1.1, .6, .8, .6, .5, 1.4, 1.0, .5,
            .6, 1.0, 1.0, 1.5, 1.4, 1.2, .3
        ],dtype=float)
        best=0.0
        kept=[]
        for item in list(self.failure_feedback):
            age=max(0.0,now-float(item.get('ts',now)))
            # Expire very old prototypes; failures remain influential for long
            # sessions but are not permanent across changed traffic regimes.
            if age > 4.0*self.failure_memory_half_life:
                continue
            fx=np.asarray(item.get('x',[]),dtype=np.float64)
            if fx.shape != x.shape:
                continue
            dist=float(np.sqrt(np.average((x-fx)**2,weights=w)))
            sim=float(math.exp(-((dist/max(.05,self.failure_memory_sigma))**2)))
            sim*=float(0.5**(age/max(60.0,self.failure_memory_half_life)))
            # Attribution confidence already controls SGD weight. Once the
            # outcome tracker has causally tied a crash to this GREEN, an exact
            # replay of that state should be blocked immediately. Validated
            # successes can later reduce `relief` and reopen that region.
            sim*=float(np.clip(item.get('relief',1.0),.20,1.0))
            best=max(best,sim)
            kept.append(item)
        self.failure_feedback=deque(kept,maxlen=self.failure_feedback.maxlen)
        return float(np.clip(best,0.0,1.0))

    def record_green_feedback(self, event):
        """Directly train the V5 decision state from an acted GREEN result.

        Retrospective lane-clear labels are useful background data, but they
        must not drown out the strongest label available: a user actually
        acted on this GREEN and either landed or crashed.
        """
        if not event or event.get('outcome') not in ('success','failure'):
            return 0
        # V5.3.8: direct SafeWindow feedback must have a real observed action
        # and remain inside the one-jump ownership envelope.
        if (
            bool(event.get('weak_action_attribution',False))
            or str(event.get('attribution','')) == 'crash_progress_fallback'
            or event.get('one_jump_valid') is False
        ):
            return 0
        vec=event.get('v5_feature_vector')
        if vec is None:
            return 0
        try:
            x=np.asarray(vec,dtype=np.float64)
        except Exception:
            return 0
        if x.shape[0] != len(self.FEATURE_NAMES) or not np.all(np.isfinite(x)):
            return 0
        conf=float(np.clip(event.get('attribution_confidence',1.0),.35,1.0))
        post=float(max(0.0,event.get('post_green_delay',0.0) or 0.0))
        # Post-GREEN motion is still causal when the outcome tracker explicitly
        # attributed it to the signal, but down-weight very late execution.
        delay_scale=float(np.clip(1.0-.18*post,.55,1.0))
        if event.get('outcome') == 'failure':
            weight=4.0*conf*delay_scale
            self._train_one(x,0,weight=weight)
            self.failure_feedback.append({
                'ts':float(event.get('outcome_ts',time.time())),
                'x':x.tolist(),
                'weight':float(np.clip(conf*delay_scale,.45,1.0)),
                'relief':1.0,
                'signal_id':event.get('signal_id'),
            })
            self.feedback_failures += 1
        else:
            self._train_one(x,1,weight=2.0*conf)
            self.feedback_successes += 1
            # A real successful jump in a previously failed neighbourhood is
            # counter-evidence. Reduce, rather than permanently delete, that
            # failure memory so long training can recover from old regimes.
            w=np.asarray([
                1.5,.5,.7,1.1,.6,.8,.6,.5,1.4,1.0,.5,.6,1.0,1.0,1.5,1.4,1.2,.3
            ],dtype=float)
            for item in self.failure_feedback:
                fx=np.asarray(item.get('x',[]),dtype=np.float64)
                if fx.shape != x.shape:
                    continue
                dist=float(np.sqrt(np.average((x-fx)**2,weights=w)))
                raw=float(math.exp(-((dist/max(.05,self.failure_memory_sigma))**2)))
                if raw >= .72:
                    item['relief']=max(.20,float(item.get('relief',1.0))*.62)
        self.save()
        return 1

    def _update_pending(self, now: float, s: dict):
        unsafe = self._unsafe_observed(s)
        lane = str(s.get('lane','-'))
        labelled = []
        for p in list(self.pending):
            if p['done']:
                continue
            # A lane/viewport transition means we can no longer observe the
            # future of the original target. Drop it instead of inventing an
            # UNSAFE label.
            if lane != p['lane']:
                p['done'] = True
                continue
            # Do not manufacture labels across a jump, viewport shift or target
            # re-anchor. The old V5 learner could label the wrong lane as SAFE.
            if (
                int(s.get('viewport_rebase_count',0) or 0) != int(p.get('viewport_rebase_count',0))
                or int(s.get('target_lane_switches',0) or 0) != int(p.get('target_switches',0))
                or bool(s.get('tracking_rewarm',False))
                or bool(s.get('sensor_desync',False))
            ):
                p['done'] = True
                continue
            if unsafe:
                p['safe'] = False
            if int(s.get('manual_failures',0) or 0) > int(p.get('manual_failures',0)):
                p['safe'] = False
            if int(s.get('crashes_learned',0) or 0) > int(p.get('crashes_learned',0)):
                p['safe'] = False
            if int(s.get('green_failures_learned',0) or 0) > int(p.get('green_failures_learned',0)):
                p['safe'] = False
            if now >= p['deadline']:
                self._train_one(p['x'], 1 if p['safe'] else 0)
                p['done'] = True
                labelled.append('SAFE' if p['safe'] else 'UNSAFE')
        self.pending = deque([p for p in self.pending if not p['done']], maxlen=self.max_pending)
        return '|'.join(labelled)

    def _maybe_add_candidate(self, now: float, s: dict, x: np.ndarray, hard_ok: bool):
        if not hard_ok or now-self.last_candidate < self.candidate_interval:
            return
        if str(s.get('lane','-')) == '-' or not bool(s.get('chicken_fresh',True)):
            return
        self.pending.append({
            'start': now, 'deadline': now+self.horizon, 'lane': str(s.get('lane')),
            'x': x.copy(), 'safe': True, 'done': False,
            'viewport_rebase_count': int(s.get('viewport_rebase_count',0) or 0),
            'target_switches': int(s.get('target_lane_switches',0) or 0),
            'manual_failures': int(s.get('manual_failures',0) or 0),
            'crashes_learned': int(s.get('crashes_learned',0) or 0),
            'green_failures_learned': int(s.get('green_failures_learned',0) or 0),
        })
        self.last_candidate = now

    def apply(self, s: dict, now: float | None = None):
        if not self.enabled:
            return s
        now = time.time() if now is None else float(now)
        label_event = self._update_pending(now, s)
        x = self._features(s)
        commit_candidate_key=(
            str(s.get('lane','-')),
            int(self._f(s.get('target_lane_switches'),0.0)),
            int(self._f(s.get('viewport_rebase_count'),0.0)),
        )
        base_hard_ok, base_hard_reason = self._hard_veto(s)
        hard_ok, hard_reason = bool(base_hard_ok), str(base_hard_reason)
        self._maybe_add_candidate(now, s, x, hard_ok)
        prob, mode = self._predict(s, x)
        threshold = self._threshold(s)
        provenance=self._gap_provenance(s)
        verified_gap_held=bool(
            hard_ok
            and self._commit_active
            and self._verified_hold_until > now
            and self._verified_hold_key == commit_candidate_key
            and self._verified_active_cycle is not None
        )
        if verified_gap_held and provenance == 'observed-clear':
            # Keep the same already-verified physical gap authoritative for its
            # remaining bounded action lease. Do not immediately fall back to
            # the stricter 1.58 s forecast rule one frame after GREEN starts.
            provenance='verified-gap'
        slow_hist_risk=self._historical_slow_after_risk(s)
        required_eta=self._required_eta_for_green(s,provenance,slow_hist_risk)
        policy_eta=(
            self._observed_clear_policy_eta(s)
            if provenance == 'observed-clear'
            else self._f(s.get('effective_eta'),0.0)
        )
        sustained_observed_ready=bool(
            hard_ok and provenance == 'observed-clear'
            and self._sustained_observed_clear_ready(
                s, self.last_heuristic_probability
            )
        )
        if sustained_observed_ready:
            # Strong observed-clear evidence may bypass collapsed ML/duplicate
            # commit dwell, but it does NOT lower the physical ETA requirement.
            required_eta=max(required_eta,self.sustained_observed_min_eta)
        if provenance not in ('verified-gap','slow-before') and slow_hist_risk > 0:
            threshold=min(.97,threshold+self.forecast_slow_after_threshold_penalty*slow_hist_risk)
        failure_similarity=self._failure_similarity(x,now)
        if failure_similarity > 0:
            prob=max(0.0, prob-self.failure_memory_prob_penalty*failure_similarity)
            threshold=min(.97,threshold+.010*failure_similarity)
        if hard_ok and failure_similarity >= self.failure_memory_hard_similarity:
            hard_ok=False
            hard_reason='LEARNED GREEN FAILURE'
        if hard_ok and policy_eta < required_eta:
            hard_ok=False
            hard_reason=('VERIFIED ETA' if provenance in ('verified-gap','slow-before','legacy') else 'FORECAST ETA')
        if hard_ok and provenance == 'observed-clear':
            current_clear=self._f(s.get('motion_current_clear_elapsed'),0.0)
            current_gap_p25=self._f(s.get('motion_gap_p25'),0.0)
            if current_clear < self.observed_clear_min_elapsed:
                hard_ok=False
                hard_reason='CLEAR MATURITY'
            elif current_gap_p25 < self.observed_clear_min_gap_p25:
                hard_ok=False
                hard_reason='CLEAR GAP HISTORY'
            elif (
                slow_hist_risk >= self.historical_slow_after_risk_trigger
                and current_gap_p25 < self.historical_slow_after_current_gap_floor
            ):
                hard_ok=False
                hard_reason='SLOW-AFTER PROFILE'

        observed_physical_ready=bool(
            hard_ok and provenance == 'observed-clear'
            and self._observed_clear_physical_ready(s, required_eta, prob)
        )
        cycle_id = int(s.get('dynamic_gap_cycle_id', 0) or 0)
        verified_gap_fastpath = bool(
            provenance == 'verified-gap'
            and (bool(s.get('dynamic_gap_ready', False)) or verified_gap_held)
        )
        verified_physical_ready=bool(
            hard_ok and verified_gap_fastpath
            and self._verified_gap_physical_ready(s, self.last_heuristic_probability)
        )

        # V5.4.3 ADAPTIVE VERIFIED-GAP LEASE.
        # Strong live physics can use the smaller presentation reserve because
        # dynamic_gap_required_eta already contains reaction + pipeline + jump +
        # safety. Weaker/ML-only verified states retain a larger reserve.
        verified_lease_tier=''
        verified_lease_required=0.0
        if hard_ok and verified_gap_fastpath:
            cycle=int(self._f(s.get('dynamic_gap_cycle_id'),0.0))
            continuing=bool(
                self._commit_active
                and self._verified_active_cycle is not None
                and cycle == self._verified_active_cycle
            )
            if verified_physical_ready:
                verified_lease_tier='strong-physical'
                verified_lease_required=self._verified_gap_physical_lease_requirement(s)
            else:
                verified_lease_tier='standard'
                verified_lease_required=self._verified_gap_lease_requirement(s)
            if (not continuing) and self._f(s.get('dynamic_gap_action_lease'),0.0) < verified_lease_required:
                hard_ok=False
                hard_reason='ACTION LEASE'
                verified_physical_ready=False

        # Hybrid confidence gate. Weak/unverified forecasts keep the learned
        # threshold. Strong live verified evidence can admit GREEN even when
        # the retrospective long-term/session ML prior has collapsed.
        difficulty=self._effective_difficulty(s)
        physical_floor=self._physical_probability_floor(provenance,difficulty,slow_hist_risk)
        admission_threshold=float(threshold)
        if hard_ok and physical_floor is not None:
            admission_threshold=min(admission_threshold,float(physical_floor))
        physical_override=bool(
            hard_ok and (
                (physical_floor is not None and prob >= admission_threshold and prob < threshold)
                or observed_physical_ready
                or verified_physical_ready
                or sustained_observed_ready
            )
        )
        v4_green = bool(s.get('green_evidence_ok', False))
        v4_reason = str(s.get('green_evidence_reason',''))

        calibrated = bool(self.n >= self.min_samples)
        raw_decision = bool(
            hard_ok and calibrated
            and (
                prob >= admission_threshold
                or observed_physical_ready
                or verified_physical_ready
                or sustained_observed_ready
            )
        )

        # V5.2.3: convert a noisy per-frame classification into a committed
        # physical-window signal.  A new target/viewport frame always starts a
        # fresh candidate.  Difficulty increases the confirmation dwell modestly
        # so late-game GREENs must be at least as stable as early-game GREENs.
        commit_required=float(np.clip(
            self.green_commit_base + self.green_commit_hard_add*difficulty,
            float(self.cfg.get('green_commit_min_seconds', .36)),
            float(self.cfg.get('green_commit_max_seconds', .42)),
        ))
        if verified_gap_fastpath:
            # RiskEngine has already observed the busy->clear transition,
            # validated remaining gap, visibility, MOG, raw risk and action
            # lease. A second ~0.3 s dwell here was consuming the opportunity.
            commit_required = min(
                commit_required, self.verified_gap_commit_seconds
            )
        elif sustained_observed_ready:
            # V5.4.0 strong observed-clear already requires >=1.0 s continuous
            # clear dwell plus mature gap history; another commit dwell would
            # duplicate the evidence and miss the window.
            commit_required = 0.0
        commit_key=commit_candidate_key
        if commit_key != self._commit_key:
            self._commit_key=commit_key
            self._commit_since=None
            self._commit_last_good=None
            self._commit_started=None
            self._commit_active=False
            self._verified_active_cycle=None
            self._verified_hold_until=0.0
            self._verified_hold_key=None

        active_green_hold_override=False
        if raw_decision:
            if self._commit_since is None:
                self._commit_since=now
            self._commit_last_good=now
            commit_elapsed=max(0.0,now-self._commit_since)
            if (not self._commit_active) and commit_elapsed >= commit_required:
                self._commit_active=True
                self._commit_started=now
                if verified_gap_fastpath:
                    self._verified_active_cycle = cycle_id
                    lease=max(0.0,self._f(s.get('dynamic_gap_action_lease'),0.0))
                    self._verified_hold_until = now + min(
                        self.verified_gap_hold_max, lease
                    )
                    self._verified_hold_key = commit_key
        else:
            commit_elapsed=(0.0 if self._commit_since is None else max(0.0,now-self._commit_since))
            if not hard_ok:
                # V5.4.0: policy-only ETA/source maturity flips may not turn a
                # just-committed GREEN into a one-frame flash. Real physical
                # hard vetoes from _hard_veto remain immediate.
                visible_age=(
                    0.0 if self._commit_started is None
                    else max(0.0,now-self._commit_started)
                )
                policy_only_reason=hard_reason in (
                    'FORECAST ETA','VERIFIED ETA','CLEAR MATURITY',
                    'CLEAR GAP HISTORY','SLOW-AFTER PROFILE'
                )
                active_green_hold_override=bool(
                    self._commit_active
                    and bool(base_hard_ok)
                    and policy_only_reason
                    and visible_age < self.green_min_visible_hold
                    and policy_eta >= self.active_green_hold_min_eta
                )
                if not active_green_hold_override:
                    self._commit_since=None
                    self._commit_last_good=None
                    self._commit_started=None
                    self._commit_active=False
                    self._verified_active_cycle=None
                    self._verified_hold_until=0.0
                    self._verified_hold_key=None
            elif self._commit_active:
                soft_age=(1e9 if self._commit_last_good is None else max(0.0,now-self._commit_last_good))
                eta_now=self._f(s.get('effective_eta'),0.0)
                visible_age=(
                    0.0 if self._commit_started is None
                    else max(0.0,now-self._commit_started)
                )
                # During the short minimum-visible lease, hard_ok is already
                # authoritative. Do not let an ML/provenance score discontinuity
                # turn a matured GREEN into a 0.15 s flash.
                if visible_age < self.green_min_visible_hold:
                    soft_ok=True
                else:
                    soft_ok=bool(
                        prob >= max(0.0,admission_threshold-self.green_commit_exit_margin)
                        and eta_now >= self.absolute_eta+self.green_commit_exit_eta_margin
                        and soft_age <= self.green_commit_dropout_grace
                    )
                if not soft_ok:
                    self._commit_since=None
                    self._commit_last_good=None
                    self._commit_started=None
                    self._commit_active=False
                    self._verified_active_cycle=None
                    self._verified_hold_until=0.0
                    self._verified_hold_key=None
            else:
                # V5.2.6: preserve sustained GREEN while matching observed safe-window duration.  Do not
                # restart the sustained commit for a tiny one-frame probability
                # dip while every hard veto is still clear.  This is bounded and
                # only applies before GREEN is visible; hard hazards still reset
                # immediately above.
                soft_age=(1e9 if self._commit_last_good is None else max(0.0,now-self._commit_last_good))
                precommit_soft_ok=bool(
                    self._commit_since is not None
                    and prob >= max(0.0,admission_threshold-self.green_precommit_exit_margin)
                    and self._f(s.get('effective_eta'),0.0) >= self.absolute_eta
                    and soft_age <= self.green_precommit_dropout_grace
                )
                if not precommit_soft_ok:
                    self._commit_since=None
                    self._commit_last_good=None

        commit_elapsed=(0.0 if self._commit_since is None else max(0.0,now-self._commit_since))
        decision=bool(self._commit_active and (hard_ok or active_green_hold_override))
        commit_age=(0.0 if self._commit_started is None else max(0.0,now-self._commit_started))

        # One physical gap -> one fresh V5 authorization. Existing outcome/
        # indicator layers still control the displayed signal lease/rearm.
        if decision and cycle_id and self.last_cycle_authorized == cycle_id:
            decision = True
        elif decision and cycle_id:
            self.last_cycle_authorized = cycle_id

        s['v5_safe_probability'] = float(prob)
        s['v5_gap_provenance'] = str(provenance)
        s['v5_required_eta'] = float(required_eta)
        s['v5_historical_slow_after_risk'] = float(slow_hist_risk)
        s['v5_safe_threshold'] = float(threshold)
        s['v5_admission_threshold'] = float(admission_threshold)
        s['v5_effective_difficulty'] = float(difficulty)
        s['v5_physical_override'] = bool(physical_override)
        s['v5_observed_clear_override'] = bool(observed_physical_ready)
        s['v5_verified_physical_override'] = bool(verified_physical_ready)
        s['v5_heuristic_probability'] = float(self.last_heuristic_probability)
        s['v5_longterm_probability'] = (None if self.last_longterm_probability is None else float(self.last_longterm_probability))
        s['v5_session_probability'] = (None if self.last_session_probability is None else float(self.last_session_probability))
        s['v5_session_train_n'] = int(self.session_n)
        s['v5_session_train_safe'] = int(self.session_safe_n)
        s['v5_session_train_unsafe'] = int(self.session_unsafe_n)
        s['v5_verified_gap_fastpath'] = bool(verified_gap_fastpath)
        s['v5_verified_gap_action_lease'] = self._f(s.get('dynamic_gap_action_lease'),0.0)
        s['v5_verified_gap_min_action_lease'] = float(self._verified_gap_lease_requirement(s))
        s['v5_verified_gap_physical_min_action_lease'] = float(self._verified_gap_physical_lease_requirement(s))
        _deg_margin,_deg_headroom=self._degraded_frame_margin(s)
        s['v5_degraded_lease_headroom'] = float(_deg_headroom)
        s['v5_degraded_frame_margin'] = float(_deg_margin)
        s['v5_verified_gap_lease_tier'] = str(verified_lease_tier)
        s['v5_verified_gap_selected_lease_required'] = float(verified_lease_required)
        _vmp=self._mode_verified_profile(s)
        s['v5_mode_physical_min_support'] = int(_vmp['support'])
        s['v5_mode_physical_min_confidence'] = float(_vmp['confidence'])
        s['v5_mode_physical_min_gap_p25'] = float(_vmp['gap_p25'])
        s['v5_verified_gap_held'] = bool(verified_gap_held)
        s['v5_verified_gap_hold_remaining'] = float(max(0.0,self._verified_hold_until-now))
        s['v5_sustained_observed_override'] = bool(sustained_observed_ready)
        s['v5_active_green_hold_override'] = bool(active_green_hold_override)
        s['v5_post_pass_settle_required'] = float(self._post_pass_settle_requirement(s))
        s['v5_post_pass_clear_elapsed'] = float(self._post_pass_clear_elapsed(s))
        s['v5_recent_threat_age'] = float(self._f(s.get('recent_threat_age'),1e9))
        s['v5_threat_tail_settle_required'] = float(
            self._threat_tail_settle_requirement(s)
        )
        s['v5_threat_tail_ready'] = bool(self._threat_tail_ready(s))
        s['v5_post_pass_ready'] = bool(
            (not bool(s.get('dynamic_gap_ready',False)))
            or self._post_pass_clear_elapsed(s) >= self._post_pass_settle_requirement(s)
        )
        s['v5_policy_eta'] = float(policy_eta)
        s['v5_observed_clear_guard_eta'] = float(
            self._observed_clear_policy_eta(s)
        )
        s['v5_feature_vector'] = x.tolist()
        s['v5_failure_similarity'] = float(failure_similarity)
        s['v5_feedback_failures'] = int(self.feedback_failures)
        s['v5_feedback_successes'] = int(self.feedback_successes)
        s['v5_safe_mode'] = mode
        s['v5_train_samples'] = int(self.n)
        s['v5_train_safe'] = int(self.safe_n)
        s['v5_train_unsafe'] = int(self.unsafe_n)
        s['v5_hard_ok'] = bool(hard_ok)
        s['v5_hard_reason'] = str(hard_reason)
        s['v5_calibrated'] = bool(calibrated)
        s['v5_shadow_v4_green'] = bool(v4_green)
        s['v5_shadow_v4_reason'] = v4_reason
        s['v5_raw_decision'] = bool(raw_decision)
        s['v5_commit_elapsed'] = float(commit_elapsed)
        s['v5_commit_required'] = float(commit_required)
        s['v5_committed'] = bool(self._commit_active)
        s['v5_commit_age'] = float(commit_age)
        s['v5_decision'] = bool(decision)

        # V5 is the GREEN soft-decision authority.  Main.py can still veto for
        # viewport, target geometry, processing and outcome/rearm conditions.
        if decision:
            s['green_evidence_ok'] = True
            s['green_evidence_reason'] = ''
            s['eta_source'] = 'v5-safe-window'
            # The legacy indicator receives required_eta_override from the V4
            # state. Replace that old learned V4 requirement with V5's hard
            # physical minimum so the V5 decision is not vetoed a second time.
            s['green_required_eta'] = float(
                self.active_green_hold_min_eta
                if active_green_hold_override else required_eta
            )
        else:
            s['green_evidence_ok'] = False
            if not hard_ok:
                s['green_evidence_reason'] = f"V5 {hard_reason}"
            elif not calibrated:
                s['green_evidence_reason'] = f"V5 CALIBRATE {self.n}/{self.min_samples}"
            elif raw_decision and not self._commit_active:
                s['green_evidence_reason'] = f"V5 COMMIT {commit_elapsed:.2f}/{commit_required:.2f}s"
            else:
                s['green_evidence_reason'] = f"V5 P{int(100*prob)}<{int(100*admission_threshold)}"

        self._writer.writerow([
            now, f'{prob:.5f}', f'{threshold:.5f}', int(decision), int(hard_ok),
            hard_reason, int(v4_green), v4_reason, self._f(s.get('effective_eta')),
            self._f(s.get('stage_difficulty_score')), cycle_id,
            self.n, self.safe_n, self.unsafe_n, label_event,
            f'{failure_similarity:.5f}', self.feedback_failures, self.feedback_successes,
            int(raw_decision), f'{commit_elapsed:.4f}', f'{commit_required:.4f}',
            int(self._commit_active), f'{commit_age:.4f}',
            provenance, f'{required_eta:.4f}', f'{slow_hist_risk:.5f}',
            f'{admission_threshold:.5f}', f'{difficulty:.5f}', int(physical_override), int(observed_physical_ready), int(verified_physical_ready),
            f'{self.last_heuristic_probability:.5f}',
            '' if self.last_longterm_probability is None else f'{self.last_longterm_probability:.5f}',
            '' if self.last_session_probability is None else f'{self.last_session_probability:.5f}',
            self.session_n,self.session_safe_n,self.session_unsafe_n,
            int(verified_gap_fastpath),
            f'{self._f(s.get("dynamic_gap_action_lease"),0.0):.4f}',
            f'{self._verified_gap_lease_requirement(s):.4f}',
            f'{self._verified_gap_physical_lease_requirement(s):.4f}',
            verified_lease_tier,
            f'{verified_lease_required:.4f}',
            self._difficulty_mode(s),
            f'{self._f(s.get("difficulty_mode_score"),0.5):.4f}',
            int(self._f(s.get('difficulty_mode_switches'),0.0)),
            int(verified_gap_held),
            f'{max(0.0,self._verified_hold_until-now):.4f}',
            int(sustained_observed_ready),
            int(active_green_hold_override),
            f'{policy_eta:.4f}',
            f'{self._observed_clear_policy_eta(s):.4f}',
            f'{self._f(s.get("czn_session_speed_guard_reference"),0.0):.2f}',
            int(self._f(s.get("czn_session_speed_support"),0.0)),
            f'{self._post_pass_settle_requirement(s):.4f}',
            f'{self._post_pass_clear_elapsed(s):.4f}',
            int(self._post_pass_clear_elapsed(s) >= self._post_pass_settle_requirement(s)),
            f'{self._f(s.get("recent_threat_age"),1e9):.4f}',
            f'{self._threat_tail_settle_requirement(s):.4f}',
            int(self._threat_tail_ready(s))
        ])
        # Buffered telemetry: flushing every inference frame adds avoidable
        # filesystem latency. Flush at ~1 Hz; model save remains independent.
        if now-self.last_log_flush > 1.0:
            self._log_file.flush()
            self.last_log_flush = now
        if self.save_during_run and now-self.last_save > self.save_interval:
            self.save()
            self.last_save = now
        return s

    def save(self):
        try:
            joblib.dump({
                'scaler': self.scaler, 'model': self.model, 'fitted': self.fitted,
                'n': self.n, 'safe_n': self.safe_n, 'unsafe_n': self.unsafe_n,
                'feature_names': tuple(self.FEATURE_NAMES), 'model_version':'v532',
                'failure_feedback': list(self.failure_feedback),
                'feedback_failures': self.feedback_failures,
                'feedback_successes': self.feedback_successes,
                'feedback_policy_version': 550,
            }, self.model_path)
        except Exception:
            pass

    def _load_failure_seed(self):
        """Load failure prototypes reconstructed from the user's latest run.

        These are not generic negative labels and they do not replace online
        learning. They simply prevent V5.2.3 from repeating the four exact
        GREEN contexts that the 2026-10-10 logs proved could crash while the
        old learner discarded them as ineligible.
        """
        try:
            if not self.failure_seed_path.exists():
                return
            obj=json.loads(self.failure_seed_path.read_text(encoding='utf-8'))
            existing={str(x.get('seed_id')) for x in self.failure_feedback if x.get('seed_id') is not None}
            for item in obj.get('failures',[]) or []:
                sid=str(item.get('seed_id',''))
                vec=item.get('x')
                if not sid or sid in existing or not isinstance(vec,list) or len(vec)!=len(self.FEATURE_NAMES):
                    continue
                self.failure_feedback.append({
                    'ts':float(time.time()),
                    'x':[float(v) for v in vec],
                    'weight':1.0,
                    'relief':1.0,
                    'signal_id':item.get('signal_id'),
                    'seed_id':sid,
                })
                existing.add(sid)
        except Exception:
            pass

    def _load(self):
        try:
            source=self.model_path
            if not source.exists():
                source=next((x for x in self.legacy_model_paths if x.exists()), self.model_path)
            if source.exists():
                obj = joblib.load(source)
                if tuple(obj.get('feature_names',())) != tuple(self.FEATURE_NAMES):
                    return
                self.scaler = obj['scaler']
                self.model = obj['model']
                self.fitted = bool(obj.get('fitted',False))
                self.n = int(obj.get('n',0))
                self.safe_n = int(obj.get('safe_n',0))
                self.unsafe_n = int(obj.get('unsafe_n',0))
                _feedback_policy_version=int(obj.get('feedback_policy_version',0) or 0)
                self.feedback_failures=int(obj.get('feedback_failures',0))
                self.feedback_successes=int(obj.get('feedback_successes',0))
                for item in obj.get('failure_feedback',[]) or []:
                    if isinstance(item,dict) and len(item.get('x',[])) == len(self.FEATURE_NAMES):
                        self.failure_feedback.append(item)
                # V5.4.0: policy <540 may contain V5.3.7 crash-fallback
                # prototypes that were not causally observed GREEN actions.
                # Drop direct failure memory once; preserve the long-term
                # retrospective classifier and validated success count.
                if _feedback_policy_version < 550:
                    # Pre-550 direct failure prototypes may contain post-landing
                    # false negatives. Preserve the retrospective classifier and
                    # validated success count, but rebuild direct GREEN failure
                    # memory under the corrected landing policy.
                    self.failure_feedback.clear()
                    self.feedback_failures=0
                # One-time v531/v530/v529/v528/v527/v526 -> v532 migration keeps the useful thousands
                # of retrospective traffic labels; direct failure memory starts
                # fresh unless it was already stored by v522.
                if source != self.model_path:
                    self.save()
        except Exception:
            pass
