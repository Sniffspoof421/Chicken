from .gap_forecast import GapForecast
import math
import time
from collections import defaultdict, deque
import numpy as np
import cv2
from app.adaptive import AdaptiveSessionModel


class RiskEngine:
    """One-lane predictive jump model.

    V3.3 evaluates ONLY the immediate next lane for the displayed jump decision.
    Farther lanes remain available to the learner historically, but they cannot
    block CLEAR for the jump being considered now.
    """

    def __init__(self, cfg):
        self.lookahead = float(cfg.get('lookahead_seconds', 3.5))
        self.crossing_half_height = float(cfg.get('crossing_half_height_px', 48))
        self.min_track_age = int(cfg.get('min_track_age', 3))
        self.jump_time = float(cfg.get('jump_crossing_seconds', .50))
        self.jump_delay = float(cfg.get('jump_start_delay_seconds', .04))
        self.safety = float(cfg.get('safety_buffer_seconds', .20))
        self.second_lane_pause = float(cfg.get('second_lane_pause_seconds', .10))
        self.prewarn = float(cfg.get('prewarn_seconds', 1.35))
        self.lane_x_tolerance = float(cfg.get('lane_x_tolerance_px', 75))

        # V4.2 physical convention:
        # screen Y increases downward; cars enter from TOP and move +Y.
        self.traffic_direction_y = 1
        self.min_approach_vy = float(cfg.get('min_approach_vy_px_s', 12.0))
        self.train_interval = float(cfg.get('train_interval_seconds', .24))
        self.second_lane_weight = float(cfg.get('second_lane_weight', .62))
        self.pattern_weight = float(cfg.get('pattern_weight', .18))
        self.clear_zone_enabled = bool(cfg.get('clear_zone_eta_enabled', True))
        self.clear_zone_min_visible_px = float(cfg.get('clear_zone_min_visible_px', 230))
        self.clear_zone_speed_percentile = float(cfg.get('clear_zone_speed_percentile', 90))
        self.clear_zone_safety_factor = float(cfg.get('clear_zone_safety_factor', 0.88))
        self.clear_zone_top_ratio = float(cfg.get('clear_zone_top_ratio', 0.06))
        self.clear_zone_bottom_ratio = float(cfg.get('clear_zone_bottom_ratio', 0.74))
        self.clear_zone_direction_min_samples = int(cfg.get('clear_zone_direction_min_samples', 12))

        # V4.2.2: CZN cannot be a GREEN source until the CURRENT post-reset
        # traffic segment has enough confirmed +Y vehicle crossings.
        self.czn_min_confirmed_events = int(
            cfg.get('czn_min_confirmed_events', 6)
        )
        self.czn_raw_min_samples = int(
            cfg.get('czn_raw_min_samples', 16)
        )
        self.czn_raw_min_unique_tracks = int(
            cfg.get('czn_raw_min_unique_tracks', 8)
        )
        self.czn_raw_track_min_samples = int(
            cfg.get('czn_raw_track_min_samples', 2)
        )
        self.czn_raw_window_seconds = float(
            cfg.get('czn_raw_window_seconds', 45.0)
        )
        self.czn_min_warmup_seconds = float(
            cfg.get('czn_min_warmup_seconds', 4.0)
        )
        self.czn_startup_speed_floor = float(
            cfg.get('czn_startup_speed_floor_px_s', 300.0)
        )
        # V5.4.1: an apparently empty lane must remember how fast cars have
        # actually been in THIS game. A 180 s quiet window must not fall back to
        # the startup 350 px/s floor after the session has already seen 700+ px/s.
        # This guard is used only for untracked observed-clear ETA; verified
        # busy->clear dynamic gaps keep their direct timing authority.
        self.czn_session_guard_min_events = int(
            cfg.get('czn_session_guard_min_events', 12)
        )
        self.czn_session_guard_percentile = float(
            cfg.get('czn_session_guard_percentile', 80.0)
        )
        self.czn_session_guard_margin = float(
            cfg.get('czn_session_guard_margin', 1.02)
        )
        self.czn_session_guard_max = float(
            cfg.get('czn_session_guard_max_px_s', 800.0)
        )
        self.czn_speed_percentile = float(
            cfg.get('czn_speed_percentile', 95.0)
        )
        self.czn_speed_margin = float(
            cfg.get('czn_speed_margin', 1.08)
        )
        self.czn_max_speed_reference = float(
            cfg.get('czn_max_speed_reference_px_s', 750.0)
        )
        # V5.3.4: historical traffic is only a bounded bootstrap prior for CZN
        # speed. It must never permanently pin the physical ETA to an old
        # session's fastest regime. Once live evidence exists, current-session
        # event/raw speeds become authoritative.
        self.czn_history_bootstrap_max_ratio = float(
            cfg.get('czn_history_bootstrap_max_ratio', 1.25)
        )
        self.czn_history_bootstrap_max_add = float(
            cfg.get('czn_history_bootstrap_max_add_px_s', 90.0)
        )
        self.czn_history_one_live_max_ratio = float(
            cfg.get('czn_history_one_live_max_ratio', 1.12)
        )
        self.czn_history_one_live_max_add = float(
            cfg.get('czn_history_one_live_max_add_px_s', 50.0)
        )
        self.pattern_green_min_segment_events = int(
            cfg.get('pattern_green_min_segment_events', 6)
        )

        self._raw_incoming_speeds = deque(maxlen=900)
        self._raw_track_last_sample = {}
        self._raw_track_samples = defaultdict(lambda: deque(maxlen=12))
        self._czn_calibrated_latched = False
        self._czn_calibration_mode = 'WAIT'
        self._czn_reset_at = time.time()

        # V3.8 observability/evidence gates.
        self.lane_visibility_half_width = int(cfg.get('lane_visibility_half_width_px', 58))
        self.lane_visibility_min_mean = float(cfg.get('lane_visibility_min_mean_gray', 38))
        self.lane_visibility_max_mean = float(cfg.get('lane_visibility_max_mean_gray', 185))
        self.lane_visibility_max_dark = float(cfg.get('lane_visibility_max_dark_ratio', .48))
        self.lane_visibility_max_bright = float(cfg.get('lane_visibility_max_bright_ratio', .58))
        self.lane_visibility_min_score = float(cfg.get('lane_visibility_min_score', .62))
        self.clear_dwell_min = float(cfg.get('clear_dwell_min_seconds', .55))
        self.recent_threat_cooldown = float(cfg.get('recent_threat_cooldown_seconds', .55))
        self.czn_unvalidated_min_eta = float(cfg.get('czn_unvalidated_min_eta_seconds', 1.85))
        self.czn_validated_min_eta = float(cfg.get('czn_validated_min_eta_seconds', 1.45))
        self.pattern_guard_min_support = int(cfg.get('pattern_guard_min_support', 5))
        self.pattern_guard_min_p25 = float(cfg.get('pattern_guard_min_p25_gap_seconds', .95))
        self.pattern_guard_max_fast = float(cfg.get('pattern_guard_max_next_fast_prob', .40))

        # V3.10 source-specific GREEN requirements.
        self.green_eta_visible = float(cfg.get('green_eta_visible_seconds', 1.30))
        self.green_eta_czn_validated = float(cfg.get('green_eta_czn_validated_seconds', 1.22))
        self.green_eta_czn_unvalidated = float(cfg.get('green_eta_czn_unvalidated_seconds', 1.32))
        self.green_eta_pattern = float(cfg.get('green_eta_pattern_seconds', 1.28))
        self.green_clear_dwell = float(cfg.get('green_clear_dwell_seconds', .35))
        self.green_recent_threat_cooldown = float(cfg.get('green_recent_threat_cooldown_seconds', .35))

        self._clear_since = defaultdict(lambda: None)
        self._last_threat = defaultdict(lambda: -1e9)
        self.pattern_eta_min_confidence = float(cfg.get('pattern_eta_min_confidence', .65))
        self.pattern_eta_min_support = int(cfg.get('pattern_eta_min_support', 6))
        self.pattern_eta_max_seconds = float(cfg.get('pattern_eta_max_seconds', 5.0))
        self.supervised_weight = float(cfg.get('supervised_weight', .38))  # legacy
        self.ml_max_up_adjustment = float(cfg.get('ml_max_up_adjustment', 15.0))
        self.ml_max_down_adjustment = float(cfg.get('ml_max_down_adjustment', 5.0))
        self.geometry_label_weight = float(cfg.get('geometry_label_weight', .20))
        self.geometry_training_enabled = bool(cfg.get('geometry_training_enabled', False))
        self.last_train = 0.0
        self.adaptive = AdaptiveSessionModel(cfg)

        # V4.2.4 PRECISION-FIRST policy.
        self.precision_mode = bool(cfg.get('precision_mode_enabled', True))
        self.precision_allow_czn_green = bool(
            cfg.get('precision_allow_czn_green', False)
        )
        self.precision_visible_eta = float(
            cfg.get('precision_min_visible_eta_seconds', 1.10)
        )
        self.precision_pattern_eta = float(
            cfg.get('precision_min_pattern_eta_seconds', 1.35)
        )
        self.precision_min_conf = float(
            cfg.get('precision_min_adaptive_confidence', .86)
        )
        self.precision_pattern_support = int(
            cfg.get('precision_min_pattern_support', 6)
        )
        self.precision_pattern_conf = float(
            cfg.get('precision_min_pattern_confidence', .55)
        )
        self.precision_pattern_p25 = float(
            cfg.get('precision_min_pattern_p25_gap_seconds', 1.65)
        )
        self.precision_pattern_max_fast = float(
            cfg.get('precision_max_pattern_fast_prob', .25)
        )
        self.precision_min_lane_events = int(
            cfg.get('precision_min_lane_segment_events', 2)
        )
        self.precision_min_global_events = int(
            cfg.get('precision_min_global_segment_events', 4)
        )
        self.precision_post_reset_age = float(
            cfg.get('precision_post_reset_observation_seconds', 6.0)
        )
        self.precision_direct_speed_floor = float(
            cfg.get('precision_direct_speed_floor_px_s', 390.0)
        )
        self.precision_uncertain_vertical_speed = float(
            cfg.get('precision_uncertain_vertical_speed_px_s', 16.0)
        )
        self.precision_uncertain_max_eta = float(
            cfg.get('precision_uncertain_max_eta_seconds', 2.2)
        )
        self.precision_current_pattern_support = int(
            cfg.get('precision_current_pattern_support', 2)
        )
        self.precision_current_pattern_p25 = float(
            cfg.get('precision_current_pattern_p25_gap_seconds', 1.45)
        )
        self.precision_current_pattern_max_fast = float(
            cfg.get('precision_current_pattern_max_fast_prob', .35)
        )

        # V4.2.6 guarded CZN re-enable.
        self.precision_allow_czn_green = bool(
            cfg.get('precision_allow_czn_green', True)
        )
        self.precision_czn_min_eta = float(
            cfg.get('precision_czn_min_eta_seconds', 1.30)
        )
        self.precision_czn_min_conf = float(
            cfg.get('precision_czn_min_confidence', .84)
        )
        self.precision_czn_min_clear_dwell = float(
            cfg.get('precision_czn_min_clear_dwell_seconds', 1.20)
        )
        self.precision_czn_motion_clear_dwell = float(
            cfg.get('precision_czn_motion_clear_dwell_seconds', .80)
        )
        self.precision_czn_motion_ratio_max = float(
            cfg.get('precision_czn_motion_ratio_max', .035)
        )
        self.precision_czn_visibility_min = float(
            cfg.get('precision_czn_visibility_min_score', .72)
        )
        self.precision_czn_recent_threat_age = float(
            cfg.get('precision_czn_recent_threat_age_seconds', .80)
        )
        self.precision_czn_min_lane_events = int(
            cfg.get('precision_czn_min_lane_segment_events', 4)
        )
        self.precision_czn_bad_pattern_fast = float(
            cfg.get('precision_czn_bad_pattern_fast_prob', .60)
        )
        self.precision_czn_bad_pattern_p25 = float(
            cfg.get('precision_czn_bad_pattern_p25_seconds', 1.20)
        )

        self.stage_global_min_events = int(cfg.get('stage_global_min_events', 6))
        self.stage_eta_adjust_max = float(cfg.get('stage_eta_adjust_max_seconds', .10))
        self.stage_clear_dwell_adjust_max = float(cfg.get('stage_clear_dwell_adjust_max_seconds', .45))
        self.stage_motion_dwell_adjust_max = float(cfg.get('stage_motion_dwell_adjust_max_seconds', .30))
        self.stage_conf_adjust_max = float(cfg.get('stage_conf_adjust_max', .045))
        self.crash_memory_block_score = float(cfg.get('crash_memory_block_score', .82))
        self.crash_memory_caution_score = float(cfg.get('crash_memory_caution_score', .58))
        self.max_safe_processing_gap = float(
            cfg.get('max_safe_processing_gap_seconds', .24)
        )

        # V4.3.9: screen-local lane numbers repeat after viewport movement, so
        # difficulty must come from live traffic rather than lane index alone.
        self.live_gap_window_seconds = float(cfg.get('live_gap_window_seconds', 180.0))
        self.live_gap_min_support = int(cfg.get('live_gap_min_support', 8))
        self.live_speed_easy_px_s = float(cfg.get('live_speed_easy_px_s', 120.0))
        self.live_speed_hard_px_s = float(cfg.get('live_speed_hard_px_s', 360.0))
        self.live_gap_easy_seconds = float(cfg.get('live_gap_easy_seconds', 1.10))
        self.live_gap_hard_seconds = float(cfg.get('live_gap_hard_seconds', .42))
        self.czn_live_min_confirmed = int(cfg.get('czn_live_min_confirmed_events', 1))
        self.czn_live_min_raw_tracks = int(cfg.get('czn_live_min_raw_tracks', 2))
        self.czn_live_min_raw_samples = int(cfg.get('czn_live_min_raw_samples', 4))
        self.czn_reliability_eta_penalty_max = float(cfg.get('czn_reliability_eta_penalty_max_seconds', .16))
        self.czn_postfix_min_eta = float(
            cfg.get('czn_postfix_min_eta_seconds', 1.58)
        )
        self._live_gap_history = deque(maxlen=160)

        # V5.5.3: bounded current-session gap prior. Local corridor history is
        # still reset on geometry changes; this prior survives and can only
        # assist bootstrap after the new lane has already produced several
        # completed local gaps.
        self._session_gap_prior = deque(maxlen=240)
        self.session_gap_prior_window = float(
            cfg.get('session_gap_prior_window_seconds', 180.0)
        )
        self.dynamic_gap_bootstrap_enabled = bool(
            cfg.get('dynamic_gap_bootstrap_enabled', True)
        )
        self.dynamic_gap_bootstrap_prior_min_support = int(
            cfg.get('dynamic_gap_bootstrap_prior_min_support', 10)
        )
        self.dynamic_gap_bootstrap_min_margin = float(
            cfg.get('dynamic_gap_bootstrap_min_margin_seconds', .30)
        )
        self.dynamic_gap_bootstrap_confidence_add = float(
            cfg.get('dynamic_gap_bootstrap_confidence_add', .05)
        )
        self.dynamic_gap_bootstrap_local_min_support = {
            'EASY': int(cfg.get('mode_easy_bootstrap_min_support',5)),
            'NORMAL': int(cfg.get('mode_normal_bootstrap_min_support',5)),
            'HARD': int(cfg.get('mode_hard_bootstrap_min_support',6)),
            'EXTREME': int(cfg.get('mode_extreme_bootstrap_min_support',7)),
        }
        self.dynamic_gap_bootstrap_min_p25 = {
            'EASY': float(cfg.get('mode_easy_bootstrap_min_p25_seconds',1.75)),
            'NORMAL': float(cfg.get('mode_normal_bootstrap_min_p25_seconds',1.85)),
            'HARD': float(cfg.get('mode_hard_bootstrap_min_p25_seconds',1.95)),
            'EXTREME': float(cfg.get('mode_extreme_bootstrap_min_p25_seconds',2.05)),
        }

        self._live_motion_lane = None
        self._live_motion_clear = None
        self._live_motion_clear_since = None
        self._live_motion_samples = deque(maxlen=240)
        self._live_motion_busy_since = None
        self._live_motion_cycle_id = 0
        self._gap_forecast = GapForecast()
        self._live_preceding_busy_duration = None
        self._slow_motion_gap_history = deque(maxlen=120)

        # Raw-motion cycle evidence is independent of fragile tracker IDs.
        self.motion_live_min_gap_support = int(
            cfg.get('motion_live_min_gap_support', 6)
        )
        # V4.4.3: phase-aware gap opening source. This does not wait for a
        # fixed CZN ETA; it uses the empirical recent traffic interval and only
        # fires early in a newly opened clear window.
        self.gap_open_enabled = bool(cfg.get('gap_open_enabled', True))
        self.gap_open_min_support = int(cfg.get('gap_open_min_support', 8))
        self.gap_open_min_elapsed = float(cfg.get('gap_open_min_elapsed_seconds', .06))
        self.gap_open_max_elapsed = float(cfg.get('gap_open_max_elapsed_seconds', .48))
        self.gap_open_min_busy = float(cfg.get('gap_open_min_preceding_busy_seconds', .16))
        self.gap_open_max_busy = float(cfg.get('gap_open_max_preceding_busy_seconds', 2.8))
        self.gap_open_base_remaining = float(cfg.get('gap_open_base_remaining_seconds', 1.03))
        self.gap_open_reaction = float(cfg.get('gap_open_reaction_seconds', .18))
        self.gap_open_stage_add = float(cfg.get('gap_open_stage_add_seconds', .12))
        self.gap_open_min_visibility = float(cfg.get('gap_open_min_visibility', .70))
        self.gap_open_max_raw_risk = float(cfg.get('gap_open_max_raw_risk', 22.0))
        self.gap_open_min_confidence = float(cfg.get('gap_open_min_confidence', .64))
        self.gap_open_failure_margin = float(cfg.get('gap_open_failure_margin_seconds', .14))

        # V4.4.4 DYNAMIC-GAP:
        # The busy->clear transition itself is useful evidence. We therefore
        # predict a conservative remaining horizon from the lower tail of the
        # recent gap distribution and include real pipeline latency in the
        # jump budget.
        self.dynamic_gap_enabled = bool(cfg.get('dynamic_gap_enabled', True))
        self.dynamic_gap_min_support = int(cfg.get('dynamic_gap_min_support', 10))
        self.dynamic_gap_min_elapsed = float(cfg.get('dynamic_gap_min_elapsed_seconds', .05))
        self.dynamic_gap_max_elapsed = float(cfg.get('dynamic_gap_max_elapsed_seconds', .62))
        self.dynamic_gap_human_reaction = float(cfg.get('dynamic_gap_human_reaction_seconds', .16))
        self.dynamic_gap_extra_guard = float(cfg.get('dynamic_gap_extra_guard_seconds', .06))
        self.dynamic_gap_stage_add = float(cfg.get('dynamic_gap_stage_add_seconds', .08))
        self.dynamic_gap_min_margin = float(cfg.get('dynamic_gap_min_margin_seconds', .08))
        self.dynamic_gap_min_visibility = float(cfg.get('dynamic_gap_min_visibility', .70))
        self.dynamic_gap_max_raw_risk = float(cfg.get('dynamic_gap_max_raw_risk', 18.0))
        self.dynamic_gap_recent_count = int(cfg.get('dynamic_gap_recent_count', 18))
        self.dynamic_gap_easy_quantile = float(cfg.get('dynamic_gap_easy_quantile', 22.0))
        self.dynamic_gap_hard_quantile = float(cfg.get('dynamic_gap_hard_quantile', 15.0))
        self.dynamic_gap_min_confidence = float(cfg.get('dynamic_gap_min_confidence', .70))
        self.dynamic_gap_failure_penalty_max = float(cfg.get('dynamic_gap_failure_penalty_max_seconds', .16))
        self.dynamic_gap_reaction_default = float(
            cfg.get('dynamic_gap_reaction_default_seconds', .38)
        )
        self.dynamic_gap_reaction_min = float(
            cfg.get('dynamic_gap_reaction_min_seconds', .24)
        )
        self.dynamic_gap_reaction_max = float(
            cfg.get('dynamic_gap_reaction_max_seconds', .72)
        )
        self.mode_reaction_default = {
            'EASY': float(cfg.get('mode_easy_reaction_default_seconds', .50)),
            'NORMAL': float(cfg.get('mode_normal_reaction_default_seconds', .58)),
            'HARD': float(cfg.get('mode_hard_reaction_default_seconds', .68)),
            'EXTREME': float(cfg.get('mode_extreme_reaction_default_seconds', .78)),
        }
        self.mode_reaction_max = {
            'EASY': float(cfg.get('mode_easy_reaction_max_seconds', .85)),
            'NORMAL': float(cfg.get('mode_normal_reaction_max_seconds', .95)),
            'HARD': float(cfg.get('mode_hard_reaction_max_seconds', 1.10)),
            'EXTREME': float(cfg.get('mode_extreme_reaction_max_seconds', 1.20)),
        }
        self.cfg_input_reaction_easy = float(
            cfg.get('mode_easy_input_reaction_seconds', .30)
        )
        self.cfg_input_reaction_normal = float(
            cfg.get('mode_normal_input_reaction_seconds', .34)
        )
        self.cfg_input_reaction_hard = float(
            cfg.get('mode_hard_input_reaction_seconds', .40)
        )
        self.cfg_input_reaction_extreme = float(
            cfg.get('mode_extreme_input_reaction_seconds', .46)
        )
        self.dynamic_gap_czn_cap_max_support = int(
            cfg.get('dynamic_gap_czn_cap_max_support', 9)
        )
        self.dynamic_gap_min_action_lease = float(
            cfg.get('dynamic_gap_min_action_lease_seconds', .10)
        )
        self.dynamic_gap_frame_reserve = float(
            cfg.get('dynamic_gap_frame_reserve_seconds', .08)
        )
        self.dynamic_gap_difficulty_reserve = float(
            cfg.get('dynamic_gap_difficulty_reserve_seconds', .06)
        )
        self.dynamic_gap_difficulty_credit_max = float(
            cfg.get('dynamic_gap_difficulty_credit_max_seconds', .10)
        )
        self.dynamic_gap_difficulty_credit_min_support = int(
            cfg.get('dynamic_gap_difficulty_credit_min_support', 16)
        )
        self.dynamic_gap_history_floor_prior_cap = float(
            cfg.get('dynamic_gap_history_floor_prior_cap_seconds', .18)
        )
        self.dynamic_gap_history_floor_recent_step = float(
            cfg.get('dynamic_gap_history_floor_recent_step_seconds', .12)
        )
        self.dynamic_gap_transition_backdate_fraction = float(
            cfg.get('dynamic_gap_transition_backdate_fraction', .50)
        )
        self.dynamic_gap_max_mog_ratio = float(
            cfg.get('dynamic_gap_max_mog_ratio', .10)
        )
        self.dynamic_gap_max_preceding_busy = float(
            cfg.get('dynamic_gap_max_preceding_busy_seconds', 1.40)
        )
        # V5.4.4 mode-specific dynamic-gap behavior. In harder modes the
        # historical gap P25 is naturally smaller, so safety comes from stronger
        # CURRENT-cycle confidence/lease rather than requiring an easy-mode gap
        # distribution. Easier modes can adapt upward faster when traffic opens.
        self.mode_gap_quantile = {
            'EASY': float(cfg.get('mode_easy_gap_quantile',25.0)),
            'NORMAL': float(cfg.get('mode_normal_gap_quantile',22.0)),
            'HARD': float(cfg.get('mode_hard_gap_quantile',18.0)),
            'EXTREME': float(cfg.get('mode_extreme_gap_quantile',15.0)),
        }
        self.mode_gap_min_support = {
            'EASY': int(cfg.get('mode_easy_gap_min_support',8)),
            'NORMAL': int(cfg.get('mode_normal_gap_min_support',9)),
            'HARD': int(cfg.get('mode_hard_gap_min_support',10)),
            'EXTREME': int(cfg.get('mode_extreme_gap_min_support',12)),
        }
        self.mode_gap_min_confidence = {
            'EASY': float(cfg.get('mode_easy_gap_min_confidence',.62)),
            'NORMAL': float(cfg.get('mode_normal_gap_min_confidence',.66)),
            'HARD': float(cfg.get('mode_hard_gap_min_confidence',.70)),
            'EXTREME': float(cfg.get('mode_extreme_gap_min_confidence',.74)),
        }
        self.mode_gap_max_elapsed = {
            'EASY': float(cfg.get('mode_easy_gap_max_elapsed_seconds',.95)),
            'NORMAL': float(cfg.get('mode_normal_gap_max_elapsed_seconds',.88)),
            'HARD': float(cfg.get('mode_hard_gap_max_elapsed_seconds',.80)),
            'EXTREME': float(cfg.get('mode_extreme_gap_max_elapsed_seconds',.74)),
        }
        self.mode_recent_weight = {
            'EASY': float(cfg.get('mode_easy_recent_gap_weight',.72)),
            'NORMAL': float(cfg.get('mode_normal_recent_gap_weight',.62)),
            'HARD': float(cfg.get('mode_hard_recent_gap_weight',.58)),
            'EXTREME': float(cfg.get('mode_extreme_recent_gap_weight',.55)),
        }
        self.mode_recent_up_cap = {
            'EASY': float(cfg.get('mode_easy_recent_up_cap_ratio',1.45)),
            'NORMAL': float(cfg.get('mode_normal_recent_up_cap_ratio',1.35)),
            'HARD': float(cfg.get('mode_hard_recent_up_cap_ratio',1.24)),
            'EXTREME': float(cfg.get('mode_extreme_recent_up_cap_ratio',1.16)),
        }
        self.mode_recent_down_floor = {
            'EASY': float(cfg.get('mode_easy_recent_down_floor_ratio',.72)),
            'NORMAL': float(cfg.get('mode_normal_recent_down_floor_ratio',.70)),
            'HARD': float(cfg.get('mode_hard_recent_down_floor_ratio',.66)),
            'EXTREME': float(cfg.get('mode_extreme_recent_down_floor_ratio',.60)),
        }
        self.czn_context_only_after_gap_support = int(
            cfg.get('czn_context_only_after_gap_support', 10)
        )
        self.motion_slow_busy_min = float(
            cfg.get('motion_slow_busy_min_seconds', .55)
        )
        self.motion_slow_busy_max = float(
            cfg.get('motion_slow_busy_max_seconds', 1.25)
        )
        self.motion_slow_min_support = int(
            cfg.get('motion_slow_min_support', 5)
        )
        self.motion_slow_min_p25 = float(
            cfg.get('motion_slow_min_p25_seconds', 1.15)
        )
        self.motion_slow_min_clear_dwell = float(
            cfg.get('motion_slow_min_clear_dwell_seconds', .10)
        )
        self.motion_slow_extra_margin = float(
            cfg.get('motion_slow_extra_margin_seconds', .08)
        )
        self.motion_slow_source_min_reliability = float(
            cfg.get('motion_slow_source_min_reliability', .65)
        )
        self.motion_slow_require_confirmed_event = bool(
            cfg.get('motion_slow_require_confirmed_event', True)
        )
        self.motion_slow_anchor_max_age = float(
            cfg.get('motion_slow_anchor_max_age_seconds', 2.4)
        )
        self.motion_slow_anchor_alignment = float(
            cfg.get('motion_slow_anchor_alignment_seconds', .65)
        )
        self.motion_slow_reaction_budget = float(
            cfg.get('motion_slow_reaction_budget_seconds', .38)
        )
        self.motion_slow_min_required_eta = float(
            cfg.get('motion_slow_min_required_eta_seconds', 1.30)
        )

        self.czn_prior_min_pattern_events = int(
            cfg.get('czn_prior_min_pattern_events', 100)
        )
        self.czn_prior_min_warmup_seconds = float(
            cfg.get('czn_prior_min_warmup_seconds', 6.0)
        )
        self.czn_prior_min_live_evidence = int(
            cfg.get('czn_prior_min_live_evidence', 1)
        )
        self.post_crash_hold_seconds = float(
            cfg.get('post_crash_hold_seconds', .80)
        )
        self._last_crash_at = -1e9

        # V4.3.5 learned slow-vehicle timing windows.
        self.slow_window_enabled = bool(cfg.get('slow_window_enabled', True))
        self.slow_window_min_profile_support = int(cfg.get('slow_window_min_profile_support', 6))
        self.slow_window_min_profile_conf = float(cfg.get('slow_window_min_profile_confidence', .68))
        self.slow_window_max_next_fast = float(cfg.get('slow_window_max_next_fast_prob', .35))
        self.slow_window_min_p25_gap = float(cfg.get('slow_window_min_p25_gap_seconds', .95))
        self.slow_window_speed_margin = float(cfg.get('slow_window_speed_margin', 1.28))
        self.slow_window_track_min_age = int(cfg.get('slow_window_track_min_age', 4))
        self.slow_window_lookahead = float(cfg.get('slow_window_lookahead_seconds', 8.0))
        self.slow_window_direction_consistency = float(cfg.get('slow_window_direction_consistency_min', .65))
        self.slow_window_extra_margin = float(cfg.get('slow_window_extra_margin_seconds', .12))
        self.slow_window_stage_eta_add = float(cfg.get('slow_window_stage_eta_add_seconds', .08))
        self.slow_window_fast_follow_guard = float(cfg.get('slow_window_fast_follow_guard_seconds', 1.45))
        self.slow_window_after_motion_dwell = float(cfg.get('slow_window_after_motion_dwell_seconds', .22))
        self.slow_window_after_body_gap_px = float(cfg.get('slow_window_after_body_gap_px', 10.0))
        self.slow_window_source_min_reliability = float(cfg.get('slow_window_source_min_reliability', .65))

        self._motion_clear_since = defaultdict(lambda: None)

    def notify_crash(self, crash_event):
        if crash_event:
            crash_ts = float(crash_event.get('event_time', time.time()))
            self.adaptive.on_crash(
                crash_ts,
                crash_event.get('reason', 'crash')
            )

            # V4.3.4:
            # Keep speed calibration across ordinary deaths.  Traffic continues
            # while the chicken respawns, so erasing all raw tracks/speeds on
            # every crash caused permanent CZN NOT CALIBRATED.
            #
            # Immediate clear-window evidence is still reset and GREEN is held
            # briefly after respawn.
            self._last_crash_at = crash_ts
            self._clear_since.clear()
            self._last_threat.clear()
            self._motion_clear_since.clear()

    def notify_geometry_reanchor(self):
        """Reset only short-lived corridor evidence after a lane re-phase.

        Long-term vehicle/type/crash learning is preserved.  Clear-dwell and
        raw-motion gap histories are screen-corridor specific, so carrying them
        across a chicken-authoritative geometry correction could certify the
        wrong physical lane for a few seconds.
        """
        self._clear_since.clear()
        self._last_threat.clear()
        self._motion_clear_since.clear()
        self._live_motion_lane = None
        self._live_motion_clear = None
        self._live_motion_clear_since = None
        self._live_motion_busy_since = None
        self._live_preceding_busy_duration = None
        self._live_motion_samples.clear()
        self._live_gap_history.clear()
        self._gap_forecast.reset()
        self._slow_motion_gap_history.clear()
        # Keep _session_gap_prior. It has no direct GREEN authority and only
        # helps bootstrap after strong current-lane evidence reappears.

    def notify_green_outcome(self, outcome):
        if outcome:
            self.adaptive.on_outcome(outcome)

    @staticmethod
    def _risk_from_clearance(clearance, prewarn):
        if clearance <= 0:
            return 98.0
        x = (clearance - 0.48) / 0.19
        r = 5.0 + 90.0 / (1.0 + math.exp(x))
        if clearance > prewarn:
            r = min(r, 8.0)
        return float(np.clip(r, 2.0, 99.0))

    def _window_for_lane(self, ordinal):
        if ordinal == 0:
            start = self.jump_delay
        else:
            start = self.jump_delay + self.jump_time + self.second_lane_pause
        end = start + self.jump_time
        return start, end

    def _lane_geometry(self, lane_index, lane_x, ordinal, tracks, chicken, learner, lane_mapper):
        cy = float(chicken['cy'])
        chicken_half = max(18.0, float(chicken.get('h', 60.0)) * .31)
        js, je = self._window_for_lane(ordinal)
        pjs, pje = max(0.0, js-self.safety), je+self.safety
        candidates = []
        uncertain_incoming = []

        for t in tracks:
            if int(t.get('age', 0)) < self.min_track_age:
                continue

            vy = float(t.get('vy', 0.0))
            vx = float(t.get('vx', 0.0))

            tlane = lane_mapper.lane_for(t['cx']) if lane_mapper.ready else -1
            if tlane != lane_index and abs(float(t['cx']) - lane_x) > self.lane_x_tolerance:
                continue

            car_y = float(t['cy'])
            delta = cy - car_y  # >0 means car is above chicken / upstream
            car_half = (
                float(t['h'])/2.0
                + self.crossing_half_height
                + chicken_half
            )

            # Fully below the crossing and moving farther down is already passed.
            if delta < -car_half:
                continue

            fit_vy = float(t.get('fit_vy', vy))
            net_vy = float(t.get('net_vy', vy))
            vertical_evidence = max(abs(vy), abs(fit_vy), abs(net_vy))
            verticalish = vertical_evidence >= max(
                self.precision_uncertain_vertical_speed,
                abs(vx) * .55
            )

            direction_valid = bool(
                t.get('direction_valid', vy >= self.min_approach_vy)
            )
            direction_suspicious = bool(
                t.get('direction_suspicious', False)
            )

            # A moving blob in the incoming part of the watched lane whose
            # direction estimate is inconsistent is a HARD uncertainty veto.
            # V4.2.3 Signal 16 had y move 664->750 while stored vy stayed <0.
            if (
                delta >= -car_half
                and verticalish
                and (direction_suspicious or not direction_valid)
            ):
                rough_forward_vy = max(
                    self.min_approach_vy,
                    max(v for v in (vy, fit_vy, net_vy, 0.0))
                )
                rough_eta = max(0.0, delta) / max(1.0, rough_forward_vy)
                if rough_eta <= self.precision_uncertain_max_eta:
                    uncertain_incoming.append({
                        'track': t,
                        'rough_eta': float(rough_eta),
                        'vertical_evidence': float(vertical_evidence),
                    })
                continue

            # Real traffic moves TOP -> BOTTOM (+Y). For a mature SLOW
            # anchor tolerate more lateral centroid jitter; total blob speed was
            # causing real slow +Y vehicles to disappear from the candidate set.
            if vy < self.min_approach_vy or not direction_valid:
                continue
            forward_probe = max(
                0.0, vy, float(t.get('fit_vy',vy)), float(t.get('net_vy',vy))
            )
            forward_probe_cls = learner.speed_class(forward_probe)
            lateral_ratio = .48 if forward_probe_cls == 'S' else 1.05
            if abs(vy) < abs(vx) * lateral_ratio:
                continue

            avy = max(1.0, vy)

            # For +Y traffic: entry occurs at -car_half above the chicken,
            # then center crossing, then exit at +car_half below it.
            center_eta = max(0.0, delta / avy)
            entry = max(0.0, (delta - car_half) / avy)
            exit_ = max(0.0, (delta + car_half) / avy)

            max_lookahead = (
                self.slow_window_lookahead
                if forward_probe_cls == 'S' else self.lookahead
            )
            if entry > max_lookahead or exit_ <= 0:
                continue

            if entry <= pje and exit_ >= pjs:
                clearance = -min(pje-entry, exit_-pjs)
                overlap = True
            elif entry > pje:
                clearance = entry-pje
                overlap = False
            else:
                clearance = pjs-exit_
                overlap = False

            typ = learner.vehicle_type(t)
            cls = learner.speed_class(t['speed'])
            forward_speed = max(
                0.0,
                float(t.get('vy', 0.0)),
                float(t.get('fit_vy', t.get('vy', 0.0))),
                float(t.get('net_vy', t.get('vy', 0.0))),
            )
            forward_cls = learner.speed_class(forward_speed)
            expected_type_speed = learner.type_expected_speed(typ)
            candidates.append({
                'track': t, 'entry': entry, 'exit': exit_, 'tti': center_eta,
                'clearance': float(clearance), 'overlap': overlap,
                'speed': float(t['speed']), 'class': cls,
                'forward_speed': float(forward_speed),
                'forward_class': str(forward_cls),
                'type': typ,
                'type_expected_speed': expected_type_speed,
            })

        candidates.sort(key=lambda c: (c['clearance'], c['entry']))
        direct = self._risk_from_clearance(candidates[0]['clearance'], self.prewarn) if candidates else 2.0
        type_pattern = learner.pattern_prediction(lane_index)
        speed_pattern = learner.speed_pattern_prediction(lane_index)

        # Speed-only patterns are primary because they accumulate support faster.
        pattern = speed_pattern if speed_pattern.get('ready') else type_pattern

        # Type-aware agreement can add a small confidence bonus, but never
        # replace the speed-only pattern or visible geometry.
        if speed_pattern.get('ready') and type_pattern.get('ready'):
            sg = speed_pattern.get('expected_gap')
            tg = type_pattern.get('expected_gap')
            if sg is not None and tg is not None and abs(float(sg)-float(tg)) <= .45:
                pattern = dict(speed_pattern)
                pattern['confidence'] = min(
                    1.0,
                    float(speed_pattern.get('confidence',0.0)) +
                    .10 * float(type_pattern.get('confidence',0.0))
                )

        # Pattern prior: if historical sequence expects another car to reach the
        # crossing during the planned jump, raise caution. A learned long break
        # can reduce only low/moderate uncertainty, never a visible threat.
        pattern_risk = 2.0
        if pattern.get('ready') and pattern.get('remaining') is not None:
            remaining = float(pattern['remaining'])
            slow_gap = float(pattern.get('slow_after_gap_score', 0.0))
            if -0.15 <= remaining <= pje + .35:
                pattern_risk = 62.0 + min(25.0, 25.0 * float(pattern.get('break_score', 0.0) == 0))
            elif remaining > pje:
                pattern_risk = self._risk_from_clearance(remaining-pje, self.prewarn)
                # If the same sequence repeatedly produces a usable gap and the
                # next vehicle is usually slow, keep the prior low. This can
                # NEVER suppress a visible/direct geometric threat.
                if slow_gap >= .35 and direct <= 18.0:
                    pattern_risk = min(pattern_risk, 5.0)
            elif float(pattern.get('break_score', 0.0)) > .35:
                pattern_risk = 3.0

        threat = candidates[0] if candidates else None
        if threat is not None:
            cls_score = 1.0 if threat['class'] == 'F' else .5 if threat['class'] == 'M' else 0.0
            typ_speed = threat.get('type_expected_speed') or 0.0
            entry = float(threat['entry'])
            clearance = float(threat['clearance'])
            speed = float(threat['speed'])
        else:
            cls_score = 0.0
            typ_speed = 0.0
            entry = self.lookahead
            clearance = self.lookahead
            speed = 0.0
        feat = [
            entry, clearance, speed, cls_score, float(len(candidates)),
            float(pattern.get('remaining') if pattern.get('remaining') is not None else self.lookahead),
            float(pattern.get('break_score', 0.0)), float(typ_speed),
        ]

        pattern_conf = float(pattern.get('confidence', 0.0))
        effective_pattern_weight = self.pattern_weight * pattern_conf
        base = max(
            direct,
            (1-effective_pattern_weight)*direct + effective_pattern_weight*pattern_risk
        )
        ml_prob = learner.predict_danger(feat)
        ml_risk = 2.0 if ml_prob is None else 2.0 + 97.0 * float(ml_prob)

        # V3.6: ML can ADJUST risk, not create a permanent 39% floor.
        if ml_prob is None:
            ml_adjustment = 0.0
        elif ml_prob >= .5:
            ml_adjustment = ((float(ml_prob)-.5)/.5) * self.ml_max_up_adjustment
        else:
            ml_adjustment = -((.5-float(ml_prob))/.5) * self.ml_max_down_adjustment
        ml_adjustment = float(np.clip(
            ml_adjustment,
            -self.ml_max_down_adjustment,
            self.ml_max_up_adjustment
        ))

        failure_penalty = float(
            learner.green_failure_penalty(pattern.get('sequence','-'))
        )
        risk = float(np.clip(base + ml_adjustment + failure_penalty, 2, 99))

        # Visible/direct geometry remains a hard lower bound.
        risk = max(float(direct), risk)

        visible_threat = bool(threat is not None and (threat['overlap'] or threat['clearance'] <= .25))
        return {
            'lane': int(lane_index), 'lane_x': float(lane_x), 'ordinal': ordinal,
            'risk': float(np.clip(risk, 2, 99)), 'direct_risk': direct,
            'pattern_risk': pattern_risk, 'ml_risk': float(ml_risk),
            'ml_adjustment': float(ml_adjustment),
            'pattern': pattern, 'type_pattern': type_pattern,
            'pattern_confidence': float(pattern.get('confidence', 0.0)),
            'p_next_slow': float(pattern.get('p_next_slow', 0.0)),
            'p_next_medium': float(pattern.get('p_next_medium', 0.0)),
            'p_next_fast': float(pattern.get('p_next_fast', 0.0)),
            'slow_after_gap_score': float(pattern.get('slow_after_gap_score', 0.0)),
            'green_failure_penalty': float(failure_penalty),
            'threat': threat, 'candidate_count': len(candidates),
            'candidates': candidates,
            'uncertain_incoming': uncertain_incoming,
            'uncertain_incoming_count': len(uncertain_incoming),
            'jump_start': js, 'jump_end': je, 'training_features': feat,
            'visible_threat': visible_threat,
        }

    def _train_maybe(self, learner, lane_state, density):
        if not self.geometry_training_enabled:
            return
        threat = lane_state.get('threat')
        if threat is None:
            return
        now = time.perf_counter()
        if now - self.last_train < self.train_interval:
            return
        self.last_train = now
        feat = lane_state.get('training_features')
        if feat is None:
            return
        if threat['overlap'] or threat['clearance'] <= 0:
            label = 1
        elif threat['clearance'] >= .9:
            label = 0
        else:
            return
        learner.learn_outcome(feat, label, weight=self.geometry_label_weight, source='geometry')

    def _observe_raw_incoming_speeds(self, tracks, now):
        """Sample plausible +Y vehicle vertical speeds without counting every frame."""
        now = float(now)

        # Prune old samples.
        while (
            self._raw_incoming_speeds
            and now - float(self._raw_incoming_speeds[0][0])
                > self.czn_raw_window_seconds
        ):
            self._raw_incoming_speeds.popleft()

        active_ids = set()
        for t in tracks:
            tid = int(t.get('id', -1))
            active_ids.add(tid)

            age = int(t.get('age', 0))
            vy = float(t.get('vy', 0.0))
            vx = float(t.get('vx', 0.0))

            if age < self.min_track_age:
                continue
            if vy < self.min_approach_vy:
                continue
            if abs(vy) < abs(vx) * 1.05:
                continue
            if not np.isfinite(vy):
                continue

            # Reject impossible tracker spikes from the calibration pool.
            if vy < 20.0 or vy > self.czn_max_speed_reference * 1.35:
                continue

            last = float(self._raw_track_last_sample.get(tid, -1e9))
            if now - last < .35:
                continue

            self._raw_track_last_sample[tid] = now
            self._raw_incoming_speeds.append((now, float(vy)))
            self._raw_track_samples[tid].append((now, float(vy)))

        # Prevent the per-track sampling map from growing forever.
        if len(self._raw_track_last_sample) > 2000:
            self._raw_track_last_sample = {
                tid: ts for tid, ts in self._raw_track_last_sample.items()
                if tid in active_ids or now - float(ts) < 5.0
            }

        # Drop stale per-track calibration histories.
        stale = []
        for tid, samples in list(self._raw_track_samples.items()):
            while samples and now - float(samples[0][0]) > self.czn_raw_window_seconds:
                samples.popleft()
            if not samples:
                stale.append(tid)
        for tid in stale:
            self._raw_track_samples.pop(tid, None)

    @staticmethod
    def _safe_percentile(values, pct, default):
        vals = np.asarray(
            [float(v) for v in values if np.isfinite(float(v))],
            dtype=float
        )
        if len(vals) == 0:
            return float(default)

        # Trim only extreme pathological spikes; preserve genuinely fast cars.
        if len(vals) >= 12:
            hi = float(np.percentile(vals, 99))
            vals = vals[vals <= hi]
        if len(vals) == 0:
            return float(default)
        return float(np.percentile(vals, pct))

    def _czn_speed_context(
        self, tracks, segment_events, traffic, fast_thr, now,
        historical_event_count=0, historical_speed_p95=None,
        session_events=None
    ):
        """Live CZN calibration using independent evidence sources.

        V4.2.2 required 12 confirmed crossing events and used a rolling event
        window. In the supplied run that counter reached only 9, then decreased.
        V4.2.3 uses cumulative current-segment crossings and can also calibrate
        from multiple mature +Y track histories.
        """
        now = float(now)
        self._observe_raw_incoming_speeds(tracks, now)

        event_speeds = [
            float(e.get('speed', 0.0))
            for e in (segment_events or [])
            if e.get('speed') is not None
            and np.isfinite(float(e.get('speed', 0.0)))
            and 20.0 <= float(e.get('speed', 0.0))
                <= self.czn_max_speed_reference * 1.35
        ]

        raw_speeds = [
            float(v) for ts, v in self._raw_incoming_speeds
            if now - float(ts) <= self.czn_raw_window_seconds
        ]

        # Treat each tracker ID approximately once by using its recent median.
        # This prevents one long-lived track from pretending to be many
        # independent vehicles.
        track_speeds = []
        for tid, samples in list(self._raw_track_samples.items()):
            vals = [
                float(v) for ts, v in samples
                if now - float(ts) <= self.czn_raw_window_seconds
            ]
            if len(vals) >= self.czn_raw_track_min_samples:
                track_speeds.append(float(np.median(vals)))

        event_p95 = self._safe_percentile(
            event_speeds,
            self.czn_speed_percentile,
            self.czn_startup_speed_floor
        )
        raw_p95 = self._safe_percentile(
            track_speeds if track_speeds else raw_speeds,
            self.czn_speed_percentile,
            self.czn_startup_speed_floor
        )

        regime_p90 = float(
            traffic.get('speed_p90', fast_thr)
            if traffic else fast_thr
        )
        if not np.isfinite(regime_p90):
            regime_p90 = float(fast_thr)

        confirmed_n = len(event_speeds)
        raw_n = len(raw_speeds)
        unique_tracks = len(track_speeds)
        warmup_age = max(0.0, now - self._czn_reset_at)
        warmup_ok = warmup_age >= self.czn_min_warmup_seconds

        confirmed_ready = confirmed_n >= self.czn_min_confirmed_events
        raw_ready = (
            raw_n >= self.czn_raw_min_samples
            and unique_tracks >= self.czn_raw_min_unique_tracks
        )

        # Strong persisted traffic history can bootstrap calibration after a
        # short live warmup.  It still needs at least one piece of live evidence
        # (a mature raw track or a confirmed crossing), and raw-motion corridor
        # verification remains mandatory before GREEN.
        prior_live_evidence = int(unique_tracks) + int(confirmed_n)
        prior_ready = bool(
            int(historical_event_count) >= self.czn_prior_min_pattern_events
            and warmup_age >= self.czn_prior_min_warmup_seconds
            and prior_live_evidence >= self.czn_prior_min_live_evidence
        )

        if not self._czn_calibrated_latched and warmup_ok:
            if confirmed_ready:
                self._czn_calibrated_latched = True
                self._czn_calibration_mode = 'EVENTS'
            elif raw_ready:
                self._czn_calibrated_latched = True
                self._czn_calibration_mode = 'RAW'
            elif prior_ready:
                self._czn_calibrated_latched = True
                self._czn_calibration_mode = 'PRIOR'

        calibrated = bool(self._czn_calibrated_latched)

        # V5.3.4 CURRENT-SESSION CZN SPEED AUTHORITY.
        #
        # The V5.3.3 run proved a deterministic deadlock: old/stage p95 was
        # ~741 px/s, so a ~635 px clear corridor could never exceed ~0.8 s ETA,
        # while V5 required >=1.08 s. The live raw/event evidence in that same
        # run was much slower. Historical speed therefore remains useful only
        # as a bounded cold-start prior; it is not a permanent max().
        live_refs = [
            self.czn_startup_speed_floor,
            max(40.0, regime_p90),
        ]
        if event_speeds:
            live_refs.append(event_p95)
        if track_speeds or raw_speeds:
            live_refs.append(raw_p95)

        live_speed_ref = float(np.clip(
            max(live_refs) * self.czn_speed_margin,
            40.0, self.czn_max_speed_reference
        ))

        historical_p95 = None
        try:
            if historical_speed_p95 is not None:
                hp = float(historical_speed_p95)
                if np.isfinite(hp) and hp > 0.0:
                    historical_p95 = hp
        except Exception:
            historical_p95 = None

        live_support = int(confirmed_n) + int(unique_tracks)
        speed_ref = float(live_speed_ref)
        speed_source = 'LIVE'
        historical_prior_applied = False
        if historical_p95 is not None and live_support <= 0:
            hist_cap = min(
                float(historical_p95),
                float(live_speed_ref) * self.czn_history_bootstrap_max_ratio,
                float(live_speed_ref) + self.czn_history_bootstrap_max_add,
            )
            if hist_cap > speed_ref:
                speed_ref = float(hist_cap)
                speed_source = 'LIVE+BOUNDED_HISTORY'
                historical_prior_applied = True
        elif historical_p95 is not None and live_support == 1:
            hist_cap = min(
                float(historical_p95),
                float(live_speed_ref) * self.czn_history_one_live_max_ratio,
                float(live_speed_ref) + self.czn_history_one_live_max_add,
            )
            if hist_cap > speed_ref:
                speed_ref = float(hist_cap)
                speed_source = 'LIVE+TAPERED_HISTORY'
                historical_prior_applied = True

        speed_ref = float(np.clip(
            speed_ref, 40.0, self.czn_max_speed_reference
        ))

        # Current-session fast-speed guard. Prefer forward (+Y) velocity stored
        # in confirmed crossing events; fall back to confirmed magnitude.
        session_speeds=[]
        for e in (session_events or []):
            try:
                v=float(e.get('forward_speed', e.get('speed',0.0)) or 0.0)
            except Exception:
                continue
            if (
                np.isfinite(v)
                and 80.0 <= v <= self.czn_max_speed_reference*1.35
            ):
                session_speeds.append(v)
        session_guard_ref=0.0
        if len(session_speeds) >= self.czn_session_guard_min_events:
            session_guard_ref=float(np.percentile(
                np.asarray(session_speeds,dtype=float),
                self.czn_session_guard_percentile
            ))
            session_guard_ref=float(np.clip(
                session_guard_ref*self.czn_session_guard_margin,
                speed_ref,
                self.czn_session_guard_max
            ))
        observed_clear_speed_ref=float(max(speed_ref,session_guard_ref))

        return {
            'calibrated': calibrated,
            'calibration_mode': self._czn_calibration_mode,
            'confirmed_events': int(confirmed_n),
            'required_events': int(self.czn_min_confirmed_events),
            'raw_samples': int(raw_n),
            'unique_raw_tracks': int(unique_tracks),
            'required_unique_tracks': int(self.czn_raw_min_unique_tracks),
            'event_p95': float(event_p95),
            'raw_p95': float(raw_p95),
            'regime_p90': float(regime_p90),
            'speed_reference': float(speed_ref),
            'live_speed_reference': float(live_speed_ref),
            'historical_speed_p95': historical_p95,
            'historical_prior_applied': bool(historical_prior_applied),
            'speed_reference_source': str(speed_source),
            'live_speed_support': int(live_support),
            'session_speed_support': int(len(session_speeds)),
            'session_speed_guard_reference': float(session_guard_ref),
            'observed_clear_speed_reference': float(observed_clear_speed_ref),
            'warmup_age': float(warmup_age),
            'warmup_required': float(self.czn_min_warmup_seconds),
            'prior_support': int(historical_event_count),
            'prior_ready': bool(prior_ready),
        }


    def _update_live_motion_profile(self, lane_key, motion_view, now):
        """Learn clear/busy traffic cycles directly from raw lane motion."""
        available = bool(motion_view.get('available', False))
        clear_now = bool(motion_view.get('clear', False)) if available else None

        if self._live_motion_lane != int(lane_key):
            self._live_motion_lane = int(lane_key)
            self._live_motion_clear = None
            self._live_motion_clear_since = None
            self._live_motion_busy_since = None
            self._live_preceding_busy_duration = None

        if available:
            now=float(now)
            self._live_motion_samples.append((now, 0 if clear_now else 1))

            if self._live_motion_clear is None:
                self._live_motion_clear = clear_now
                if clear_now:
                    self._live_motion_clear_since = now
                else:
                    self._live_motion_busy_since = now

            elif clear_now != self._live_motion_clear:
                if self._live_motion_clear:
                    # clear -> busy: finalize completed clear gap
                    if self._live_motion_clear_since is not None:
                        clear_dur=max(
                            0.0,now-float(self._live_motion_clear_since)
                        )
                        if .18 <= clear_dur <= 8.0:
                            self._live_gap_history.append(
                                (now,float(clear_dur))
                            )
                            self._session_gap_prior.append(
                                (now,int(lane_key),float(clear_dur))
                            )
                            pb=self._live_preceding_busy_duration
                            if (
                                pb is not None
                                and self.motion_slow_busy_min <= float(pb)
                                    <= self.motion_slow_busy_max
                            ):
                                self._slow_motion_gap_history.append(
                                    (now,float(pb),float(clear_dur))
                                )
                    self._live_motion_busy_since=now
                    self._live_motion_clear_since=None
                    self._live_preceding_busy_duration=None
                else:
                    # busy -> clear: this departing occupancy duration is a
                    # tracker-independent proxy for a slow vehicle.
                    busy_dur=(
                        0.0 if self._live_motion_busy_since is None
                        else max(
                            0.0,now-float(self._live_motion_busy_since)
                        )
                    )
                    self._live_preceding_busy_duration=float(busy_dur)
                    self._live_motion_cycle_id += 1
                    self._live_motion_clear_since=now
                    self._live_motion_busy_since=None

                self._live_motion_clear=clear_now

        cutoff=float(now)-self.live_gap_window_seconds
        while (
            self._live_gap_history
            and self._live_gap_history[0][0] < cutoff
        ):
            self._live_gap_history.popleft()
        while (
            self._slow_motion_gap_history
            and self._slow_motion_gap_history[0][0] < cutoff
        ):
            self._slow_motion_gap_history.popleft()
        while (
            self._live_motion_samples
            and self._live_motion_samples[0][0] < float(now)-12.0
        ):
            self._live_motion_samples.popleft()

        _prior_cutoff=float(now)-self.session_gap_prior_window
        while (
            self._session_gap_prior
            and self._session_gap_prior[0][0] < _prior_cutoff
        ):
            self._session_gap_prior.popleft()

        gaps=[g for _,g in self._live_gap_history]
        support=len(gaps)
        p10=float(np.percentile(gaps,10)) if gaps else None
        p15=float(np.percentile(gaps,15)) if gaps else None
        p20=float(np.percentile(gaps,20)) if gaps else None
        p25=float(np.percentile(gaps,25)) if gaps else None
        median=float(np.median(gaps)) if gaps else None

        recent_gaps=gaps[-max(1,self.dynamic_gap_recent_count):]
        recent_support=len(recent_gaps)
        recent_p15=(
            float(np.percentile(recent_gaps,15))
            if recent_gaps else None
        )
        recent_p20=(
            float(np.percentile(recent_gaps,20))
            if recent_gaps else None
        )
        recent_p25=(
            float(np.percentile(recent_gaps,25))
            if recent_gaps else None
        )
        gap_cv=(
            float(np.std(gaps)/max(.05,np.mean(gaps)))
            if len(gaps)>=3 else 0.0
        )

        slow_gaps=[g for _,_,g in self._slow_motion_gap_history]
        slow_support=len(slow_gaps)
        slow_p25=(
            float(np.percentile(slow_gaps,25))
            if slow_gaps else None
        )
        slow_median=(
            float(np.median(slow_gaps))
            if slow_gaps else None
        )

        busy_fraction=(
            float(np.mean([v for _,v in self._live_motion_samples]))
            if self._live_motion_samples else 0.0
        )
        current_clear_elapsed=(
            0.0
            if not clear_now or self._live_motion_clear_since is None
            else max(
                0.0,float(now)-float(self._live_motion_clear_since)
            )
        )

        motion_live_ready=bool(
            support >= self.motion_live_min_gap_support
            and .03 <= busy_fraction <= .88
        )

        prior_gaps=[g for _,_,g in self._session_gap_prior]
        prior_support=len(prior_gaps)
        prior_p15=float(np.percentile(prior_gaps,15)) if prior_gaps else None
        prior_p20=float(np.percentile(prior_gaps,20)) if prior_gaps else None
        prior_p25=float(np.percentile(prior_gaps,25)) if prior_gaps else None

        return {
            'support':support,
            'p10':p10,'p15':p15,'p20':p20,'p25':p25,'median':median,
            'recent_support':int(recent_support),
            'recent_p15':recent_p15,'recent_p20':recent_p20,
            'recent_p25':recent_p25,'gap_cv':float(gap_cv),
            'busy_fraction':busy_fraction,
            'current_clear_elapsed':float(current_clear_elapsed),
            'preceding_busy_duration':self._live_preceding_busy_duration,
            'slow_support':int(slow_support),
            'slow_p25':slow_p25,
            'slow_median':slow_median,
            'motion_live_ready':motion_live_ready,
            'cycle_id':int(self._live_motion_cycle_id),
            'session_prior_support':int(prior_support),
            'session_prior_p15':prior_p15,
            'session_prior_p20':prior_p20,
            'session_prior_p25':prior_p25,
        }


    def _live_difficulty(self, czn_ctx, motion_profile, fallback=0.0):
        """Current-session traffic difficulty with historical memory as a prior.

        V4.4.12: earlier builds used ``max(historical, live)``. That made a
        difficult late-game history a permanent lower bound on every new run,
        so level 1 could start with late-game conservatism. Keep the same
        speed/headway concept, but let sufficiently supported *current* traffic
        override stale history. Headway/density is weighted more strongly than
        raw speed because a fast but sparse lane can still have generous,
        actionable gaps.
        """
        raw_p95=float(czn_ctx.get('raw_p95',0.0) or 0.0)
        # V5.2.4: raw CZN tracks can briefly go blind exactly when the game gets
        # fast.  In the 87-minute V5.2.3 run, recent pass-event p95 reached
        # ~350 px/s while raw_p95 fell to ~33 px/s, collapsing difficulty to
        # ~0.04. Blend in the recent (180 s) event p95, but never historical
        # all-session speed, so a hard late game cannot poison a fresh early game.
        event_p95=float(czn_ctx.get('event_p95',0.0) or 0.0)
        live_p95=max(raw_p95, .90*event_p95)
        speed_score=float(np.clip(
            (live_p95-self.live_speed_easy_px_s) /
            max(1.0,self.live_speed_hard_px_s-self.live_speed_easy_px_s),
            0.0,1.0
        ))
        support=int(motion_profile.get('support',0) or 0)
        p25=motion_profile.get('p25')
        if p25 is not None and support >= self.live_gap_min_support:
            density_score=float(np.clip(
                (self.live_gap_easy_seconds-float(p25)) /
                max(.05,self.live_gap_easy_seconds-self.live_gap_hard_seconds),
                0.0,1.0
            ))
        else:
            density_score=float(np.clip(
                (float(motion_profile.get('busy_fraction',0.0))-.12)/.38,
                0.0,1.0
            ))

        live=float(np.clip(.68*density_score+.32*speed_score,0.0,1.0))

        confirmed=int(czn_ctx.get('confirmed_events',0) or 0)
        raw_tracks=int(czn_ctx.get('unique_raw_tracks',0) or 0)
        evidence=max(support, confirmed, raw_tracks)
        live_weight=float(np.clip(.35 + .055*evidence, .35, .90))
        blended=float(
            live_weight*live + (1.0-live_weight)*float(np.clip(fallback,0.0,1.0))
        )

        if support >= self.live_gap_min_support and density_score <= .20:
            blended=min(blended, .38 + .18*speed_score)

        return float(np.clip(blended,0.0,1.0)), speed_score, density_score

    def _effective_dynamic_gap_failure_floor(
        self, raw_floor, required_eta, recent_source_failures=0
    ):
        """Bound stale historical failure floors by current-session evidence."""
        raw_floor=float(raw_floor or 0.0)
        required_eta=float(required_eta or 0.0)
        recent_source_failures=max(0,int(recent_source_failures or 0))
        hist_uplift=max(0.0, raw_floor-required_eta)
        floor_cap=float(
            self.dynamic_gap_history_floor_prior_cap
            + self.dynamic_gap_history_floor_recent_step
                * min(3,recent_source_failures)
        )
        return float(required_eta + min(hist_uplift,floor_cap))

    def _incoming_motion_corridor(self, motion_mask, lane_x, chicken_y):
        """Independent foreground check for the watched TOP->chicken corridor."""
        if motion_mask is None:
            return {'available':False,'clear':False,'ratio':1.0,'reason':'NO MOTION MASK'}

        # V4.2.9 supports either the old full mask or a cropped watched-lane
        # mask with global origin metadata.
        if isinstance(motion_mask, dict):
            mask = motion_mask.get('mask')
            mog_mask = motion_mask.get('mog_mask')
            diff_mask = motion_mask.get('diff_mask')
            x0 = int(motion_mask.get('x0',0))
            y0 = int(motion_mask.get('y0',0))
            full_h = int(motion_mask.get('full_h', mask.shape[0] if mask is not None else 0))
            full_w = int(motion_mask.get('full_w', mask.shape[1] if mask is not None else 0))
        else:
            mask = motion_mask
            mog_mask = None
            diff_mask = None
            x0=y0=0
            full_h,full_w = mask.shape[:2]

        if mask is None or mask.size == 0:
            return {'available':False,'clear':False,'ratio':1.0,'reason':'EMPTY MOTION MASK'}

        x = int(round(float(lane_x)))
        hw = max(20, self.lane_visibility_half_width)
        gx1,gx2 = max(0,x-hw), min(full_w,x+hw)
        gy1 = max(0,int(full_h*self.clear_zone_top_ratio))
        gy2 = min(full_h,int(float(chicken_y)-self.crossing_half_height))

        # Intersect global desired corridor with cropped mask.
        mx1=max(0,gx1-x0); mx2=min(mask.shape[1],gx2-x0)
        my1=max(0,gy1-y0); my2=min(mask.shape[0],gy2-y0)
        if mx2-mx1 < 20 or my2-my1 < 60:
            return {'available':False,'clear':False,'ratio':1.0,'reason':'MOTION ROI NOT COVERING LANE'}

        roi=mask[my1:my2,mx1:mx2]
        ratio=float(np.count_nonzero(roi))/float(roi.size)

        def _ratio(src, corridor=False):
            if src is None or src.size == 0:
                return 0.0
            if corridor:
                rr=src[my1:my2,mx1:mx2]
                if rr.size == 0:
                    return 0.0
                return float(np.count_nonzero(rr))/float(rr.size)
            return float(np.count_nonzero(src))/float(src.size)

        mog_ratio=_ratio(mog_mask, corridor=True)
        diff_ratio=_ratio(diff_mask, corridor=True)
        mog_global_ratio=_ratio(mog_mask, corridor=False)
        diff_global_ratio=_ratio(diff_mask, corridor=False)
        clear=ratio <= self.precision_czn_motion_ratio_max
        return {
            'available':True,'clear':bool(clear),'ratio':ratio,
            'mog_ratio':float(mog_ratio),'diff_ratio':float(diff_ratio),
            'mog_global_ratio':float(mog_global_ratio),
            'diff_global_ratio':float(diff_global_ratio),
            'reason':'' if clear else 'RAW MOTION IN LANE'
        }

    def _lane_visibility(self, frame, lane_x, chicken_y):
        """Estimate whether the incoming lane corridor is genuinely visible.

        This specifically catches analyzer/console windows covering the game.
        A false 'empty lane' is never allowed to become CZN GREEN.
        """
        if frame is None:
            return {
                'ok': False, 'score': 0.0, 'mean_gray': 0.0,
                'dark_ratio': 1.0, 'reason': 'NO FRAME'
            }

        h, w = frame.shape[:2]
        x = int(round(lane_x))
        hw = max(20, self.lane_visibility_half_width)
        x1, x2 = max(0, x-hw), min(w, x+hw)

        y1 = max(0, int(h * self.clear_zone_top_ratio))
        y2 = min(h, int(float(chicken_y) - self.crossing_half_height))
        if x2-x1 < 20 or y2-y1 < 80:
            return {
                'ok': False, 'score': 0.0, 'mean_gray': 0.0,
                'dark_ratio': 1.0, 'reason': 'SMALL ROI'
            }

        roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        mean_gray = float(np.mean(gray))
        dark_ratio = float(np.mean(gray < 28))
        bright_ratio = float(np.mean(gray > 220))

        # Guard BOTH ends of the brightness range. Older builds only rejected
        # dark occlusions, so a white File Explorer window could score 1.0 and
        # masquerade as an empty road.
        low_score = float(np.clip(
            (mean_gray - self.lane_visibility_min_mean) / 45.0, 0.0, 1.0
        ))
        high_score = float(np.clip(
            (self.lane_visibility_max_mean - mean_gray) / 55.0, 0.0, 1.0
        ))
        dark_score = float(np.clip(
            (self.lane_visibility_max_dark - dark_ratio) /
            max(.08, self.lane_visibility_max_dark), 0.0, 1.0
        ))
        bright_score = float(np.clip(
            (self.lane_visibility_max_bright - bright_ratio) /
            max(.08, self.lane_visibility_max_bright), 0.0, 1.0
        ))

        # A normal mid-gray road scores well on all components. Extremely
        # bright or dark overlays are rejected even when lane geometry is stale.
        score = .30*low_score + .25*high_score + .25*dark_score + .20*bright_score
        ok = (
            mean_gray >= self.lane_visibility_min_mean
            and mean_gray <= self.lane_visibility_max_mean
            and dark_ratio <= self.lane_visibility_max_dark
            and bright_ratio <= self.lane_visibility_max_bright
            and score >= self.lane_visibility_min_score
        )
        return {
            'ok': bool(ok), 'score': float(score),
            'mean_gray': mean_gray, 'dark_ratio': dark_ratio,
            'bright_ratio': bright_ratio,
            'reason': '' if ok else 'GAME/ROAD OCCLUDED'
        }

    @staticmethod
    def _forward_vy(track):
        vals = [
            float(track.get('vy', 0.0)),
            float(track.get('fit_vy', track.get('vy', 0.0))),
            float(track.get('net_vy', track.get('vy', 0.0))),
        ]
        vals = [v for v in vals if np.isfinite(v)]
        return max([0.0] + vals)

    def _candidate_entry_bound(self, candidate, chicken, speed_floor=0.0, margin=1.18):
        tr = candidate.get('track', {})
        cy = float(chicken['cy'])
        chicken_half = max(18.0, float(chicken.get('h', 60.0)) * .31)
        car_y = float(tr.get('cy', cy))
        car_half = float(tr.get('h', 0.0))/2.0 + self.crossing_half_height + chicken_half
        delta = cy - car_y
        speed = max(
            float(speed_floor),
            self._forward_vy(tr) * float(margin),
            self.min_approach_vy
        )
        return max(0.0, (delta-car_half) / max(1.0, speed))

    def _slow_window_geometry(
        self, *, l1, chicken, slow_thr, fast_thr, profile, upstream_eta,
        motion_view, motion_clear_dwell, stage_score,
        learner=None, lane_key=None, wall_now=None
    ):
        out = {
            'mode':'', 'ok':False, 'eta':None, 'required_eta':None,
            'anchor_id':None, 'reason':'NO SLOW ANCHOR',
            'profile_ok':False,
            'profile_confidence':float(profile.get('confidence',0.0)),
            'p_fast':float(profile.get('p_fast_after_slow',1.0)),
            'p25_gap':profile.get('p25_gap'),
            'median_gap':profile.get('median_gap'),
            'support':int(profile.get('support',0)),
            'lane_support':int(profile.get('lane_support',0)),
            'profile_source':profile.get('source','none'),
            'follower_eta':None, 'departing_anchor_safe':False,
        }
        if not self.slow_window_enabled:
            out['reason']='SLOW WINDOW DISABLED'
            return out

        p25 = profile.get('p25_gap')
        pfast = float(profile.get('p_fast_after_slow',1.0))
        pconf = float(profile.get('confidence',0.0))
        support = int(profile.get('support',0))

        stage_fast_limit = max(
            .18, self.slow_window_max_next_fast - .08*float(stage_score)
        )
        stage_gap_min = (
            self.slow_window_min_p25_gap + .08*float(stage_score)
        )

        # BEFORE and AFTER a slow vehicle are different situations.
        #
        # BEFORE: the slow anchor's own measured ETA is the physical clock, so
        # historical S->next P25 does not need to exceed the full jump time.
        # We only need strong support + a sufficiently low probability of an
        # imminent FAST follower, and then check all currently visible followers.
        before_profile_ok = bool(
            profile.get('ready')
            and support >= self.slow_window_min_profile_support
            and pfast <= stage_fast_limit
            and pconf >= self.slow_window_min_profile_conf
        )

        # AFTER: now the S->next gap itself matters, so require a lower-tail
        # headway large enough to plausibly fit the crossing.
        after_profile_ok = bool(
            before_profile_ok
            and p25 is not None
            and float(p25) >= stage_gap_min
        )
        out['profile_ok'] = before_profile_ok
        out['after_profile_ok'] = after_profile_ok

        physical_min = (
            self.jump_time + self.safety + self.slow_window_extra_margin
            + self.slow_window_stage_eta_add*float(stage_score)
        )
        out['required_eta'] = float(physical_min)

        if not before_profile_ok:
            # V4.4.9: do not discard a physically verified slow vehicle just
            # because the historical S->next profile is still sparse.  The
            # previous early return made the slow-vehicle path unusable in
            # short/new sessions (exactly what the 2026-10-06 run showed).
            # We still keep the profile requirement for AFTER-slow windows,
            # but BEFORE-slow may use a stricter direct-geometry fallback.
            out['reason'] = (
                f"SLOW PROFILE S{support} F{int(100*pfast)} "
                f"G{0.0 if p25 is None else float(p25):.2f}"
            )

        candidates = list(l1.get('candidates', []))
        if int(l1.get('uncertain_incoming_count',0)) > 0:
            out['reason'] = 'SLOW UNCERTAIN VEHICLE'
            return out

        # BEFORE slow vehicle.
        before=[]
        for c in candidates:
            forward_cls_now=str(c.get('forward_class', c.get('class','M')))
            expected_type_speed_now=c.get('type_expected_speed')
            type_slow_hint=bool(
                expected_type_speed_now is not None
                and float(expected_type_speed_now) <= max(
                    float(slow_thr)*1.10, self.min_approach_vy*1.25
                )
            )
            if forward_cls_now != 'S' and not type_slow_hint:
                continue
            tr=c.get('track',{})
            if int(tr.get('age',0)) < self.slow_window_track_min_age:
                continue
            if not bool(tr.get('direction_valid',True)):
                continue
            if float(tr.get('direction_consistency',1.0)) < self.slow_window_direction_consistency:
                continue
            if float(tr.get('cy',chicken['cy'])) >= float(chicken['cy']):
                continue

            # A robust live S track can be used before the historical slow
            # profile has matured.  This fallback is deliberately stricter
            # than the learned-profile path: older track, steadier direction,
            # and a measured speed that really lies in the slow band.
            measured_forward=max(
                abs(float(tr.get('vy',0.0) or 0.0)),
                abs(float(tr.get('fit_vy',0.0) or 0.0)),
                abs(float(tr.get('net_vy',0.0) or 0.0)),
            )
            direct_slow_verified=bool(
                int(tr.get('age',0)) >= max(self.slow_window_track_min_age,5)
                and bool(tr.get('direction_valid',True))
                and float(tr.get('direction_consistency',1.0))
                    >= max(self.slow_window_direction_consistency,.72)
                and measured_forward >= max(6.0,.70*self.min_approach_vy)
                and measured_forward <= max(
                    float(slow_thr)*1.18, self.min_approach_vy*1.35
                )
            )
            # V5.2.9: use the already-learned vehicle-type speed memory as an
            # EARLY slow-anchor hint. The old slow-before path waited for the
            # current track speed itself to settle into S, which happened only
            # once in the entire 163-minute V5.2.8 run. A type hint never
            # overrides direction/follower/ETA safety and is rejected if the
            # current forward speed is clearly fast.
            expected_type_speed=c.get('type_expected_speed')
            type_slow_verified=bool(
                expected_type_speed is not None
                and int(tr.get('age',0)) >= max(self.slow_window_track_min_age,4)
                and bool(tr.get('direction_valid',True))
                and float(tr.get('direction_consistency',1.0))
                    >= max(self.slow_window_direction_consistency,.62)
                and float(expected_type_speed) <= max(
                    float(slow_thr)*1.10, self.min_approach_vy*1.25
                )
                and measured_forward <= max(float(fast_thr)*.92, float(slow_thr)*1.55)
            )
            if not before_profile_ok and not direct_slow_verified and not type_slow_verified:
                continue

            anchor_eta=self._candidate_entry_bound(
                c,chicken,
                speed_floor=max(self.min_approach_vy,float(slow_thr)*1.05),
                margin=self.slow_window_speed_margin
            )
            anchor_y=float(tr.get('cy',chicken['cy']))
            other_etas=[]
            fast_follow=False
            ambiguous_follow=False
            for o in candidates:
                if o is c:
                    continue
                otr=o.get('track',{})
                cls=str(o.get('forward_class', o.get('class','M')))
                floor=float(fast_thr) if cls=='F' else max(float(slow_thr)*1.15,self.min_approach_vy)
                oe=self._candidate_entry_bound(
                    o,chicken,speed_floor=floor,
                    margin=1.20 if cls=='F' else 1.15
                )
                other_etas.append(oe)
                if (
                    cls=='F'
                    and float(otr.get('cy',chicken['cy'])) < anchor_y
                    and oe <= anchor_eta + self.slow_window_fast_follow_guard
                ):
                    fast_follow=True
                # Without a mature historical profile, any reasonably close
                # M/F follower is treated as ambiguous rather than assuming
                # the slow anchor guarantees a safe opening.
                if (
                    not before_profile_ok
                    and cls in ('M','F')
                    and float(otr.get('cy',chicken['cy'])) < anchor_y
                    and oe <= anchor_eta + self.slow_window_fast_follow_guard
                ):
                    ambiguous_follow=True

            limiting=min([anchor_eta]+other_etas) if other_etas else anchor_eta
            direct_extra=(.18 + .10*float(stage_score)) if not before_profile_ok else 0.0
            if (
                limiting >= physical_min + direct_extra
                and not fast_follow
                and not ambiguous_follow
            ):
                # The slow anchor itself may set the generic visible_threat bit
                # even though its conservative ETA is safely outside the jump
                # window. The explicit limiting ETA above is authoritative here.
                before.append((limiting,c,other_etas))

        if before:
            before.sort(key=lambda x:x[0])
            eta,anchor,others=before[0]
            out.update({
                'mode':'slow-before','ok':True,'eta':float(eta),
                'anchor_id':int(anchor['track']['id']),'reason':'',
                'follower_eta':None if not others else float(min(others)),
                'direct_fallback': bool(not before_profile_ok),
            })
            return out

        # AFTER slow vehicle. Here historical lower-tail headway matters.
        if not after_profile_ok:
            out['reason'] = (
                f"SLOW AFTER GAP {0.0 if p25 is None else float(p25):.2f}"
                f"<{stage_gap_min:.2f}"
            )
            return out

        after=[]
        chicken_half=max(18.0,float(chicken.get('h',60.0))*.31)
        body_margin=max(
            self.slow_window_after_body_gap_px,
            float(chicken.get('h',60.0))*.06
        )
        for c in candidates:
            if str(c.get('forward_class', c.get('class','M'))) != 'S':
                continue
            tr=c.get('track',{})
            if not bool(tr.get('direction_valid',True)):
                continue
            car_y=float(tr.get('cy',chicken['cy']))
            if car_y <= float(chicken['cy']):
                continue

            body_gap=(
                car_y - float(tr.get('h',0.0))/2.0
                - (float(chicken['cy'])+chicken_half)
            )
            if body_gap < body_margin:
                continue

            other_etas=[]
            fast_follow=False
            for o in candidates:
                if o is c:
                    continue
                cls=str(o.get('forward_class', o.get('class','M')))
                floor=float(fast_thr) if cls=='F' else max(float(slow_thr)*1.15,self.min_approach_vy)
                oe=self._candidate_entry_bound(
                    o,chicken,speed_floor=floor,
                    margin=1.20 if cls=='F' else 1.15
                )
                other_etas.append(oe)
                if cls=='F' and oe <= self.slow_window_fast_follow_guard:
                    fast_follow=True

            vals=[x for x in other_etas if np.isfinite(x)]
            if upstream_eta is not None:
                vals.append(max(0.0,float(upstream_eta)))
            if not vals:
                continue
            limiting=min(vals)

            if (
                bool(motion_view.get('available',False))
                and bool(motion_view.get('clear',False))
                and float(motion_clear_dwell) >= self.slow_window_after_motion_dwell
                and limiting >= physical_min
                and not fast_follow
            ):
                after.append((limiting,c,other_etas,body_gap))

        if after:
            after.sort(key=lambda x:x[0])
            eta,anchor,others,body_gap=after[0]
            out.update({
                'mode':'slow-after','ok':True,'eta':float(eta),
                'anchor_id':int(anchor['track']['id']),'reason':'',
                'follower_eta':None if not others else float(min(others)),
                'departing_anchor_safe':True,'body_gap':float(body_gap),
            })
            return out

        # Passed vehicles are removed from live candidates, so use the
        # confirmed pass-event stream as an AFTER-SLOW anchor.
        if learner is not None and lane_key is not None:
            latest = learner.latest_lane_event(
                int(lane_key), now=float(wall_now or time.time()), seconds=2.5
            )
            if latest is not None:
                latest_cls = str(
                    latest.get('forward_class', latest.get('class','M'))
                )
                if latest_cls == 'S':
                    elapsed = max(
                        0.0,
                        float(wall_now or time.time())
                        - float(latest.get('ts', wall_now or time.time()))
                    )
                    p25 = profile.get('p25_gap')
                    remaining_p25 = (
                        None if p25 is None
                        else max(0.0, float(p25) - elapsed)
                    )

                    other_etas = []
                    fast_follow = False
                    for o in candidates:
                        cls = str(
                            o.get('forward_class', o.get('class','M'))
                        )
                        floor = (
                            float(fast_thr) if cls == 'F'
                            else max(float(slow_thr)*1.15, self.min_approach_vy)
                        )
                        oe = self._candidate_entry_bound(
                            o, chicken, speed_floor=floor,
                            margin=1.20 if cls == 'F' else 1.15
                        )
                        other_etas.append(oe)
                        if cls == 'F' and oe <= self.slow_window_fast_follow_guard:
                            fast_follow = True

                    vals = [
                        float(v) for v in other_etas
                        if np.isfinite(float(v))
                    ]
                    if upstream_eta is not None:
                        vals.append(max(0.0, float(upstream_eta)))
                    if remaining_p25 is not None:
                        vals.append(float(remaining_p25))

                    if vals:
                        limiting = min(vals)
                        if (
                            bool(profile.get('ready'))
                            and bool(out.get('after_profile_ok', False))
                            and bool(motion_view.get('available',False))
                            and bool(motion_view.get('clear',False))
                            and float(motion_clear_dwell)
                                >= self.slow_window_after_motion_dwell
                            and limiting >= float(out['required_eta'])
                            and not fast_follow
                        ):
                            out.update({
                                'mode': 'slow-after',
                                'ok': True,
                                'eta': float(limiting),
                                'anchor_id': f"pass@{float(latest.get('ts',0.0)):.3f}",
                                'reason': '',
                                'follower_eta': (
                                    None if not other_etas
                                    else float(min(other_etas))
                                ),
                                'departing_anchor_safe': True,
                                'event_elapsed': float(elapsed),
                                'event_remaining_p25': float(remaining_p25),
                            })
                            return out

        out['reason']='NO VERIFIED SLOW WINDOW'
        return out

    def evaluate(self, tracks, learner, lane_mapper, frame_shape, chicken,
                 frame=None, motion_mask=None, lane_override=None,
                 pipeline_latency_seconds=.16):
        h, w = frame_shape[:2]
        if chicken is None:
            return {
                'risk': 50.0, 'action_reason': 'chicken not detected', 'lane1': None, 'lane2': None,
                'safe_window': 0.0, 'tti': None, 'threat_id': None, 'lane': '-',
                'ml_samples': learner.supervised_n, 'pattern_events': learner.pattern_event_n,
                'pattern_text': 'WAITING FOR CHICKEN', 'chicken_ok': False,
            }

        if lane_override is not None:
            next_lanes=[(int(lane_override[0]),float(lane_override[1]))]
        else:
            next_lanes = lane_mapper.next_lanes(chicken['cx'], 1) if lane_mapper.ready else []
        if not next_lanes:
            return {
                'risk': 35.0, 'action_reason': 'learning lane positions', 'lane1': None, 'lane2': None,
                'safe_window': 0.0, 'tti': None, 'threat_id': None, 'lane': '-',
                'ml_samples': learner.supervised_n, 'pattern_events': learner.pattern_event_n,
                'pattern_text': 'LEARNING LANES', 'chicken_ok': True,
            }

        lane_states = [
            self._lane_geometry(li, lx, idx, tracks, chicken, learner, lane_mapper)
            for idx,(li,lx) in enumerate(next_lanes)
        ]
        l1 = lane_states[0]
        l2 = lane_states[1] if len(lane_states) > 1 else None

        # GREEN remains an immediate-next-lane decision. L2 is look-ahead
        # learning/context only; it cannot authorize a two-lane jump.
        risk = float(l1['risk'])

        now_perf = time.perf_counter()
        vis = self._lane_visibility(frame, l1['lane_x'], chicken['cy'])
        lane_key = int(l1['lane'])
        motion_view = self._incoming_motion_corridor(
            motion_mask, l1['lane_x'], chicken['cy']
        )

        if motion_view['available'] and motion_view['clear'] and vis['ok']:
            if self._motion_clear_since[lane_key] is None:
                self._motion_clear_since[lane_key] = now_perf
        else:
            self._motion_clear_since[lane_key] = None

        motion_clear_dwell = (
            0.0 if self._motion_clear_since[lane_key] is None
            else max(0.0, now_perf - self._motion_clear_since[lane_key])
        )

        # Motion used to be only a hidden GREEN veto, so the displayed risk
        # could sit at exactly the same percentage while cars visibly passed.
        # Make the risk meter responsive to independent foreground activity.
        motion_activity_risk = 0.0
        if motion_view.get('available',False):
            mr=float(motion_view.get('ratio',0.0))
            thr=float(self.precision_czn_motion_ratio_max)
            if mr > thr:
                motion_activity_risk=float(np.clip(
                    18.0 + 77.0*(mr-thr)/max(.05,.22-thr),
                    18.0,95.0
                ))
                risk=max(float(risk),motion_activity_risk)

        if l1.get('candidate_count', 0) > 0 or l1.get('visible_threat', False):
            self._clear_since[lane_key] = None
        elif vis['ok']:
            if self._clear_since[lane_key] is None:
                self._clear_since[lane_key] = now_perf
        else:
            self._clear_since[lane_key] = None

        if l1.get('visible_threat', False):
            self._last_threat[lane_key] = now_perf

        clear_dwell = (
            0.0 if self._clear_since[lane_key] is None
            else max(0.0, now_perf - self._clear_since[lane_key])
        )
        recent_threat_age = max(0.0, now_perf - self._last_threat[lane_key])

        # Prewarm the second lane while the chicken is still deciding L1.
        # When L2 later becomes L1, its event/pattern/clear history is already
        # live instead of starting from zero.
        l2_context = None
        if l2 is not None:
            l2_key = int(l2['lane'])
            l2_vis = self._lane_visibility(frame, l2['lane_x'], chicken['cy'])
            l2_motion = self._incoming_motion_corridor(
                motion_mask, l2['lane_x'], chicken['cy']
            )

            if (
                l2.get('candidate_count',0) == 0
                and not l2.get('visible_threat',False)
                and l2_vis['ok']
            ):
                if self._clear_since[l2_key] is None:
                    self._clear_since[l2_key] = now_perf
            else:
                self._clear_since[l2_key] = None

            if l2_motion.get('available') and l2_motion.get('clear') and l2_vis['ok']:
                if self._motion_clear_since[l2_key] is None:
                    self._motion_clear_since[l2_key] = now_perf
            else:
                self._motion_clear_since[l2_key] = None

            if l2.get('visible_threat',False):
                self._last_threat[l2_key] = now_perf

            l2_context = {
                'lane': l2_key,
                'risk': float(l2.get('risk',50.0)),
                'candidate_count': int(l2.get('candidate_count',0)),
                'visible_threat': bool(l2.get('visible_threat',False)),
                'clear_dwell': (
                    0.0 if self._clear_since[l2_key] is None
                    else max(0.0,now_perf-self._clear_since[l2_key])
                ),
                'motion_clear_dwell': (
                    0.0 if self._motion_clear_since[l2_key] is None
                    else max(0.0,now_perf-self._motion_clear_since[l2_key])
                ),
                'motion_ratio': float(l2_motion.get('ratio',1.0)),
                'pattern': l2.get('pattern',{}),
            }

        wall_now = time.time()
        live_motion_profile = self._update_live_motion_profile(
            lane_key, motion_view, wall_now
        )
        slow_thr, fast_thr = learner.speed_thresholds()
        regime_events = learner.recent_lane_events(
            lane_key, wall_now,
            seconds=max(self.adaptive.long_window + 30.0, 120.0),
            current_segment_only=False
        )
        traffic = self.adaptive.observe_traffic(
            regime_events, wall_now, slow_thr, fast_thr
        )

        # Pattern sequence timing remains current-segment only, but live traffic
        # speed calibration is intentionally rolling across ordinary crashes.
        recent_events_all = learner.recent_events_all_lanes(
            wall_now, seconds=180.0
        )
        segment_events_all = learner.current_segment_events_all_lanes()
        segment_lane_events = learner.current_segment_lane_events(lane_key)

        stage_profile = learner.lane_difficulty_profile(lane_key)
        historical_speeds = list(getattr(learner, 'event_speeds', []))
        historical_speed_p95 = (
            float(np.percentile(
                np.asarray(historical_speeds[-400:], dtype=float), 95
            ))
            if historical_speeds else None
        )

        session_events_all = learner.current_session_events_all_lanes()
        czn_ctx = self._czn_speed_context(
            tracks, recent_events_all, traffic, fast_thr, wall_now,
            historical_event_count=int(getattr(learner, 'pattern_event_n', 0)),
            historical_speed_p95=historical_speed_p95,
            session_events=session_events_all
        )
        stage2_profile = (
            learner.lane_difficulty_profile(int(l2['lane']))
            if l2 is not None else None
        )
        # V5.3.4: stage_profile is long-term context, not a physical speed
        # measurement for the current target lane. Do NOT max() it back into
        # CZN after _czn_speed_context deliberately tapered history.
        czn_ctx['stage_speed_reference'] = float(
            stage_profile.get('speed_reference',0.0)
        )
        live_stage_score, live_speed_score, live_density_score = self._live_difficulty(
            czn_ctx, live_motion_profile,
            fallback=float(stage_profile.get('difficulty',0.0))
        )
        difficulty_mode_state=self.adaptive.update_difficulty_mode(
            wall_now, live_motion_profile, live_speed_score,
            live_density_score, traffic
        )
        difficulty_mode=str(difficulty_mode_state.get('mode','NORMAL'))

        self._train_maybe(learner, l1, l1['candidate_count'])
        threat = l1.get('threat')
        safe = self.lookahead
        direct_eta = None
        threat_id = None

        # Direct ETA is the earliest visible approaching vehicle in L1, not only
        # an overlapping "threat". This improves ETA coverage during clear gaps.
        visible_etas = []
        for c in l1.get('candidates', []):
            eta = c.get('tti')
            if eta is not None and np.isfinite(float(eta)) and float(eta) >= 0:
                visible_etas.append((float(eta), c))

        visible_eta_candidate = min(visible_etas, key=lambda x: x[0]) if visible_etas else None
        if visible_eta_candidate is not None:
            direct_eta = visible_eta_candidate[0]
            eta_track = visible_eta_candidate[1]
            threat_id = int(eta_track['track']['id'])

            # V4.2.4: tracker velocity is sometimes severely underestimated.
            # Recompute a conservative ETA using a physical +Y speed floor.
            tr = eta_track['track']
            delta_y = max(0.0, float(chicken['cy']) - float(tr.get('cy', chicken['cy'])))
            measured_vy = max(0.0, float(tr.get('vy', 0.0)))
            if (
                str(eta_track.get('forward_class', eta_track.get('class','M'))) == 'S'
                and int(tr.get('age',0)) >= self.slow_window_track_min_age
                and bool(tr.get('direction_valid',True))
                and float(tr.get('direction_consistency',1.0))
                    >= self.slow_window_direction_consistency
            ):
                conservative_vy = max(
                    self._forward_vy(tr)*self.slow_window_speed_margin,
                    float(slow_thr)*1.05,
                    self.min_approach_vy,
                )
            else:
                conservative_vy = max(
                    measured_vy,
                    self.precision_direct_speed_floor,
                    float(czn_ctx.get('speed_reference',0.0)),
                )
            conservative_eta = delta_y / max(1.0, conservative_vy)
            direct_eta = min(float(direct_eta), float(conservative_eta))

            safe = max(
                0.0,
                float(eta_track['entry']) - (l1['jump_end'] + self.safety)
            )
        elif threat is not None:
            direct_eta = max(0.0, float(threat['tti']))
            threat_id = int(threat['track']['id'])
            safe = max(
                0.0,
                float(threat['entry']) - (l1['jump_end'] + self.safety)
            )

        p1 = l1.get('pattern', {})
        p2 = l2.get('pattern', {}) if l2 else {}

        # Pattern ETA is accepted only from sane, confident timing.
        pattern_eta = None
        pattern_conf = float(p1.get('confidence', 0.0))
        pattern_support = int(p1.get('support', 0))
        pattern_remaining = p1.get('remaining')
        if (
            p1.get('ready')
            and pattern_remaining is not None
            and pattern_conf >= self.pattern_eta_min_confidence
            and pattern_support >= self.pattern_eta_min_support
        ):
            pr = float(pattern_remaining)
            if 0.0 <= pr <= self.pattern_eta_max_seconds:
                pattern_eta = pr

        # DIRECTION-AWARE CLEAR-ZONE ETA LOWER BOUND:
        # V3.2 used the shorter screen edge, which systematically produced
        # ~1.3-1.4 s and blocked the 1.5 s CLEAR gate. V3.3 uses the lane's
        # learned incoming direction and measures from the actual incoming edge.
        clear_zone_eta = None
        clear_zone_direction = 0.0
        clear_zone_distance = None
        if (
            self.clear_zone_enabled
            and direct_eta is None
            and l1.get('lane_x') is not None
            and vis['ok']
            and clear_dwell >= self.clear_dwell_min
        ):
            # V4.2.2: clear-zone ETA uses the fail-safe current-segment
            # speed reference. During warmup this is intentionally conservative
            # and CZN is still blocked from producing GREEN.
            fast_speed = float(czn_ctx['speed_reference'])

            # V4.2 confirmed physical direction:
            # cars enter from TOP and move toward +Y/down the screen.
            clear_zone_direction = 1.0

            cy = float(chicken['cy'])
            frame_h = float(frame_shape[0]) if frame_shape is not None else max(cy*2.0, 720.0)
            road_top = frame_h * self.clear_zone_top_ratio

            visible_distance = max(0.0, cy - road_top)
            clear_zone_distance = visible_distance
            if visible_distance >= self.clear_zone_min_visible_px:
                clear_zone_eta = (
                    visible_distance / fast_speed
                ) * self.clear_zone_safety_factor

        # Conservative ETA from the upstream screen edge, computed even when
        # a slow anchor is visible. It verifies the gap BEHIND a departing slow
        # vehicle.
        upstream_clear_eta = None
        if self.clear_zone_enabled and vis['ok'] and l1.get('lane_x') is not None:
            cy = float(chicken['cy'])
            frame_h = float(frame_shape[0]) if frame_shape is not None else max(cy*2.0,720.0)
            road_top = frame_h*self.clear_zone_top_ratio
            visible_distance = max(0.0,cy-road_top)
            if visible_distance >= self.clear_zone_min_visible_px:
                upstream_clear_eta = (
                    visible_distance / max(1.0,float(czn_ctx['speed_reference']))
                ) * self.clear_zone_safety_factor

        # Scope the corrected profile to an actual slow anchor / recent slow
        # pass. Ordinary traffic retains its previous feature values exactly.
        _slow_pass=learner.latest_lane_event(lane_key,now=wall_now,seconds=2.5)
        _slow_context=bool(
            any(str(c.get('forward_class',c.get('class','M')))=='S'
                for c in l1.get('candidates',[]))
            or (_slow_pass is not None and str(_slow_pass.get(
                'forward_class',_slow_pass.get('class','M')))=='S'))
        slow_profile = learner.slow_anchor_profile(
            lane_key,min_lane_support=self.slow_window_min_profile_support,
            now=wall_now,directional=_slow_context
        )
        slow_window = self._slow_window_geometry(
            l1=l1,chicken=chicken,slow_thr=slow_thr,fast_thr=fast_thr,
            profile=slow_profile,upstream_eta=upstream_clear_eta,
            motion_view=motion_view,motion_clear_dwell=motion_clear_dwell,
            stage_score=float(stage_profile.get('difficulty',0.0)),
            learner=learner, lane_key=lane_key, wall_now=wall_now
        )

        # V5.2 asymmetric slow-vehicle context. Jumping BEFORE a verified
        # approaching slow vehicle can be useful because its measured arrival
        # clock is long. Jumping AFTER a slow vehicle is a different, riskier
        # state because a close follower may be hidden by the departing car.
        # Expose a recent-slow-pass guard even when the historical profile is not
        # mature enough for _slow_window_geometry() to emit slow-after.
        slow_after_guard_active=False
        recent_slow_pass_age=None
        try:
            _last_slow_evt=learner.latest_lane_event(int(lane_key),now=float(wall_now),seconds=2.8)
        except Exception:
            _last_slow_evt=None
        if _last_slow_evt is not None:
            _cls=str(_last_slow_evt.get('forward_class',_last_slow_evt.get('class','M')))
            if _cls=='S':
                recent_slow_pass_age=max(0.0,float(wall_now)-float(_last_slow_evt.get('ts',wall_now)))
                slow_after_guard_active=bool(recent_slow_pass_age <= 2.4)

        # V4.4.1 CONFIRMED-SLOW-AFTER.
        #
        # V4.4.0 treated a 0.55-1.0 s raw-motion busy period as a "slow car".
        # All four acted GREENs from that source failed. Busy duration can be
        # multiple cars, mask persistence, or road texture; it is not enough.
        #
        # Keep the useful raw-motion gap statistics, but require an ACTUAL
        # confirmed SLOW crossing aligned with the busy->clear transition.
        motion_slow_eta = None
        motion_slow_anchor_ok = False
        motion_slow_anchor_age = None
        motion_slow_anchor_alignment = None
        motion_slow_anchor_id = None

        motion_slow_required_eta = float(max(
            self.motion_slow_min_required_eta,
            self.jump_time
            + self.safety
            + self.motion_slow_extra_margin
            + self.motion_slow_reaction_budget
            + .08*float(live_stage_score)
        ))

        preceding_busy = live_motion_profile.get(
            'preceding_busy_duration'
        )
        slow_motion_p25 = live_motion_profile.get('slow_p25')
        slow_motion_support = int(
            live_motion_profile.get('slow_support',0)
        )
        current_clear_elapsed = float(
            live_motion_profile.get('current_clear_elapsed',0.0)
        )

        latest_slow_event = learner.latest_lane_event(
            lane_key, now=wall_now,
            seconds=self.motion_slow_anchor_max_age
        )
        if latest_slow_event is not None:
            event_cls = str(
                latest_slow_event.get(
                    'forward_class',
                    latest_slow_event.get('class','M')
                )
            )
            if event_cls == 'S':
                motion_slow_anchor_age = max(
                    0.0,
                    float(wall_now)
                    - float(latest_slow_event.get('ts',wall_now))
                )
                # A real pass event should occur near the start of the clear
                # interval created by that departing vehicle.
                motion_slow_anchor_alignment = abs(
                    float(motion_slow_anchor_age)
                    - float(current_clear_elapsed)
                )
                motion_slow_anchor_ok = bool(
                    motion_slow_anchor_age
                        <= self.motion_slow_anchor_max_age
                    and motion_slow_anchor_alignment
                        <= self.motion_slow_anchor_alignment
                )
                motion_slow_anchor_id = (
                    latest_slow_event.get('track_id')
                    or latest_slow_event.get('id')
                    or f"evt@{float(latest_slow_event.get('ts',0.0)):.3f}"
                )

        if (
            motion_view.get('available',False)
            and motion_view.get('clear',False)
            and preceding_busy is not None
            and self.motion_slow_busy_min <= float(preceding_busy)
                <= self.motion_slow_busy_max
            and slow_motion_support >= self.motion_slow_min_support
            and slow_motion_p25 is not None
            and float(slow_motion_p25) >= self.motion_slow_min_p25
            and current_clear_elapsed >= self.motion_slow_min_clear_dwell
            and not bool(l1.get('visible_threat',False))
            and int(l1.get('uncertain_incoming_count',0)) == 0
            and vis.get('ok',False)
            and (
                motion_slow_anchor_ok
                or not self.motion_slow_require_confirmed_event
            )
        ):
            remaining=max(
                0.0,float(slow_motion_p25)-current_clear_elapsed
            )
            limiting=remaining
            if upstream_clear_eta is not None:
                limiting=min(limiting,float(upstream_clear_eta))
            if limiting >= motion_slow_required_eta:
                motion_slow_eta=float(limiting)

        # V4.4.4 DYNAMIC-GAP predictor.
        #
        # The latest run had 613 otherwise-valid GO samples, but 467 were
        # rejected as "RISK VOLATILITY". That volatility is expected directly
        # after a vehicle passes: the trailing 0.75 s history still contains
        # the departing high-risk car. Waiting for that history to become
        # smooth consumes the useful part of the gap.
        #
        # Safety is instead expressed here as a forward-looking hazard budget:
        #   lower-tail clear-gap horizon
        # - time already consumed
        # - real processing latency
        # - human reaction allowance
        # - jump time + collision buffer
        #
        # The lower-tail quantile becomes more conservative as live traffic
        # difficulty increases or this source accumulates failures.
        dynamic_gap_eta = None
        dynamic_gap_remaining = None
        dynamic_gap_required_eta = None
        dynamic_gap_confidence = 0.0
        dynamic_gap_ready = False
        dynamic_gap_support = int(live_motion_profile.get('support',0))
        dynamic_gap_recent_support = int(
            live_motion_profile.get('recent_support',0)
        )
        gap_preceding_busy = live_motion_profile.get('preceding_busy_duration')

        dg_rel = learner.green_source_reliability(
            'dynamic-gap', lane=None
        )
        dg_rate = float(
            dg_rel.get('global_rate',dg_rel.get('rate',.8))
        )
        dg_fail_pressure = float(np.clip(
            (.78-dg_rate)/.48,0.0,1.0
        ))

        # V5.4.4 explicit mode quantile. Difficulty no longer depends on a
        # slowly drifting scalar alone; the hysteretic mode decides which tail
        # of the learned gap distribution is appropriate. Source failures can
        # still move the chosen quantile more conservative.
        _mode_q=float(self.mode_gap_quantile.get(difficulty_mode,22.0))
        dynamic_gap_quantile = float(np.clip(
            _mode_q - 3.0*dg_fail_pressure,
            12.0,25.0
        ))

        def _interp_quantile(prefix=''):
            p15=live_motion_profile.get(prefix+'p15')
            p20=live_motion_profile.get(prefix+'p20')
            p25=live_motion_profile.get(prefix+'p25')
            if p15 is None:
                return None
            q=dynamic_gap_quantile
            if q <= 20.0 or p25 is None:
                if p20 is None:
                    return float(p15)
                a=float(np.clip((q-15.0)/5.0,0.0,1.0))
                return float(p15)+(float(p20)-float(p15))*a
            a=float(np.clip((q-20.0)/5.0,0.0,1.0))
            return float(p20)+(float(p25)-float(p20))*a

        long_lower=_interp_quantile('')
        recent_lower=_interp_quantile('recent_')
        dynamic_gap_recent_weight=0.0
        dynamic_gap_regime_direction='long-only'
        if (
            long_lower is not None
            and recent_lower is not None
            and dynamic_gap_recent_support >= 6
        ):
            # V5.4.4 ASYMMETRIC MODE ADAPTATION. Old code fixed recent weight
            # at 35% and capped easing at +12%, so a hard regime poisoned the
            # next easier section for many minutes. Hardening now reacts even
            # faster; easing requires the mode's hysteresis first, then recent
            # completed gaps are allowed to move the predictor decisively.
            recent_w=float(self.mode_recent_weight.get(difficulty_mode,.62))
            if float(recent_lower) < float(long_lower):
                recent_w=max(recent_w,.74)
                dynamic_gap_regime_direction='hardening'
            elif float(recent_lower) > float(long_lower)*1.04:
                dynamic_gap_regime_direction='easing'
            else:
                dynamic_gap_regime_direction='stable'
            dynamic_gap_recent_weight=recent_w
            mixed=(1.0-recent_w)*float(long_lower)+recent_w*float(recent_lower)
            dynamic_gap_lower_bound=float(np.clip(
                mixed,
                float(self.mode_recent_down_floor.get(difficulty_mode,.70))*float(long_lower),
                float(self.mode_recent_up_cap.get(difficulty_mode,1.35))*float(long_lower)
            ))
        else:
            dynamic_gap_lower_bound=long_lower

        # V5.5.3 strict post-reanchor bootstrap.
        prior_support=int(live_motion_profile.get('session_prior_support',0))
        prior_p15=live_motion_profile.get('session_prior_p15')
        prior_p20=live_motion_profile.get('session_prior_p20')
        prior_p25=live_motion_profile.get('session_prior_p25')

        def _prior_quantile():
            if prior_p15 is None:
                return None
            q=dynamic_gap_quantile
            if q <= 20.0 or prior_p25 is None:
                if prior_p20 is None:
                    return float(prior_p15)
                a=float(np.clip((q-15.0)/5.0,0.0,1.0))
                return float(prior_p15)+(float(prior_p20)-float(prior_p15))*a
            a=float(np.clip((q-20.0)/5.0,0.0,1.0))
            return float(prior_p20)+(float(prior_p25)-float(prior_p20))*a

        prior_lower=_prior_quantile()
        _mode_min_support=int(
            self.mode_gap_min_support.get(
                difficulty_mode,self.dynamic_gap_min_support
            )
        )
        _bootstrap_local_min=int(
            self.dynamic_gap_bootstrap_local_min_support.get(
                difficulty_mode,max(5,_mode_min_support-4)
            )
        )
        _bootstrap_p25_min=float(
            self.dynamic_gap_bootstrap_min_p25.get(
                difficulty_mode,1.85
            )
        )
        _local_p25=live_motion_profile.get('p25')
        dynamic_gap_bootstrap_candidate=bool(
            self.dynamic_gap_bootstrap_enabled
            and dynamic_gap_support < _mode_min_support
            and dynamic_gap_support >= _bootstrap_local_min
            and dynamic_gap_recent_support >= _bootstrap_local_min
            and prior_support >= self.dynamic_gap_bootstrap_prior_min_support
            and recent_lower is not None
            and prior_lower is not None
            and _local_p25 is not None
            and float(_local_p25) >= _bootstrap_p25_min
        )
        dynamic_gap_bootstrap_lower=None
        if dynamic_gap_bootstrap_candidate:
            # Prior can never make the new lane look better than its own recent
            # completed gaps.
            dynamic_gap_bootstrap_lower=float(
                min(float(recent_lower),float(prior_lower))
            )
            if (
                dynamic_gap_lower_bound is None
                or dynamic_gap_bootstrap_lower > float(dynamic_gap_lower_bound)
            ):
                dynamic_gap_lower_bound=float(dynamic_gap_bootstrap_lower)

        measured_pipeline=float(np.clip(
            float(pipeline_latency_seconds or .16),.06,.24
        ))
        # V5.4.7: movement-confirmation delay is not human click latency.
        # Keep it only as diagnostic outcome timing; do not feed it back into
        # the physical pre-jump ETA budget.
        dynamic_gap_observed_action_delay=learner.source_action_delay_budget(
            'dynamic-gap',
            default=self.dynamic_gap_reaction_default,
            min_delay=self.dynamic_gap_reaction_min,
            max_delay=max(
                self.dynamic_gap_reaction_max,
                max(self.mode_reaction_max.values())
            )
        )
        dynamic_gap_reaction_budget=float({
            'EASY': self.cfg_input_reaction_easy,
            'NORMAL': self.cfg_input_reaction_normal,
            'HARD': self.cfg_input_reaction_hard,
            'EXTREME': self.cfg_input_reaction_extreme,
        }.get(difficulty_mode,self.cfg_input_reaction_normal))
        dynamic_gap_physical_floor=float(
            self.jump_time
            + self.safety
            + dynamic_gap_reaction_budget
            + measured_pipeline
        )
        dynamic_gap_base_required=float(
            dynamic_gap_physical_floor
            + self.dynamic_gap_extra_guard
            + self.dynamic_gap_stage_add*float(live_stage_score)
        )

        dg_maturity=float(np.clip(
            (dynamic_gap_support-self.dynamic_gap_difficulty_credit_min_support)
            / max(1.0,float(self.dynamic_gap_difficulty_credit_min_support)),
            0.0,1.0
        ))
        dg_relief_reliability=float(np.clip(
            (dg_rate-.60)/.30, 0.0,1.0
        ))
        dg_hardness=float(np.clip(
            (float(live_stage_score)-.42)/.40, 0.0,1.0
        ))
        dynamic_gap_difficulty_credit=float(
            self.dynamic_gap_difficulty_credit_max
            * dg_maturity * dg_relief_reliability * dg_hardness
        )
        dynamic_gap_required_eta=float(max(
            dynamic_gap_physical_floor,
            dynamic_gap_base_required-dynamic_gap_difficulty_credit
        ))

        # V5.5.11: mode easing is learned for subsequent gaps. It cannot
        # manufacture extra time in an already open physical traffic gap.
        dynamic_gap_unlatched_lower_bound = dynamic_gap_lower_bound
        dynamic_gap_lower_bound, dynamic_gap_required_eta = self._gap_forecast.update(
            (lane_key, int(live_motion_profile.get('cycle_id', 0))),
            bool(motion_view.get('available') and motion_view.get('clear')),
            dynamic_gap_lower_bound, dynamic_gap_required_eta)

        dynamic_gap_effective_clear_elapsed=max(
            0.0,
            float(current_clear_elapsed)
            - self.dynamic_gap_transition_backdate_fraction
                * float(measured_pipeline)
        )

        _bootstrap_headroom_ok=False
        if dynamic_gap_lower_bound is not None:
            dynamic_gap_remaining=max(
                0.0,
                float(dynamic_gap_lower_bound)
                - float(dynamic_gap_effective_clear_elapsed)
            )

            # Mature live-gap learning must not be hard-capped by the
            # viewport's near-constant ~1.44 s CZN geometry.
            _bootstrap_headroom_ok=bool(
                dynamic_gap_bootstrap_candidate
                and dynamic_gap_bootstrap_lower is not None
                and dynamic_gap_bootstrap_lower
                    >= dynamic_gap_required_eta
                        + self.dynamic_gap_bootstrap_min_margin
            )
            if (
                upstream_clear_eta is not None
                and dynamic_gap_support
                    <= self.dynamic_gap_czn_cap_max_support
                and not _bootstrap_headroom_ok
            ):
                dynamic_gap_remaining=min(
                    float(dynamic_gap_remaining),
                    float(upstream_clear_eta)
                )

        # V4.4.13: the main required ETA already contains jump + safety +
        # learned reaction + measured pipeline latency.  V4.4.12 subtracted
        # jump/safety/pipeline here and then required reaction+pipeline again,
        # effectively counting human response and processing latency twice.
        # The lease now means only the *extra* usable margin after the full
        # required ETA, with a small frame/difficulty reserve.
        dynamic_gap_lease_required=float(max(
            self.dynamic_gap_min_action_lease,
            self.dynamic_gap_frame_reserve
            + self.dynamic_gap_difficulty_reserve*float(live_stage_score)
        ))

        dynamic_gap_action_lease = (
            None if dynamic_gap_remaining is None
            else max(
                0.0,
                float(dynamic_gap_remaining)
                - float(dynamic_gap_required_eta)
            )
        )

        # V4.4.9: generic motion-gap logic must never overrule a live
        # approaching S anchor.  Low-speed vehicles produce less foreground
        # energy and can make the corridor look deceptively empty.  Route such
        # cases through the explicit slow-before geometry instead.
        approaching_slow_guard=False
        for _c in list(l1.get('candidates', [])):
            _tr=_c.get('track',{})
            _cls=str(_c.get('forward_class',_c.get('class','M')))
            if (
                _cls=='S'
                and int(_tr.get('age',0)) >= max(2,self.slow_window_track_min_age-1)
                and bool(_tr.get('direction_valid',True))
                and float(_tr.get('direction_consistency',1.0)) >= .58
                and float(_tr.get('cy',chicken['cy'])) < float(chicken['cy'])
            ):
                approaching_slow_guard=True
                break

        if (
            self.dynamic_gap_enabled
            and not approaching_slow_guard
            and motion_view.get('available',False)
            and motion_view.get('clear',False)
            and (
                dynamic_gap_support >= _mode_min_support
                or bool(_bootstrap_headroom_ok)
            )
            and gap_preceding_busy is not None
            and self.gap_open_min_busy <= float(gap_preceding_busy)
                <= self.dynamic_gap_max_preceding_busy
            and float(motion_view.get('mog_global_ratio',0.0))
                <= self.dynamic_gap_max_mog_ratio
            and self.dynamic_gap_min_elapsed
                <= float(current_clear_elapsed)
                <= float(self.mode_gap_max_elapsed.get(
                    difficulty_mode,self.dynamic_gap_max_elapsed
                ))
            and dynamic_gap_remaining is not None
            and float(dynamic_gap_remaining)
                >= dynamic_gap_required_eta+self.dynamic_gap_min_margin
            and dynamic_gap_action_lease is not None
            and float(dynamic_gap_action_lease)
                >= max(
                    self.dynamic_gap_min_action_lease,
                    float(dynamic_gap_lease_required)
                )
            and float(vis.get('score',0.0))
                >= self.dynamic_gap_min_visibility
            and not bool(l1.get('visible_threat',False))
            and int(l1.get('uncertain_incoming_count',0)) == 0
            and float(risk) <= self.dynamic_gap_max_raw_risk
        ):
            _support_den=(
                _bootstrap_local_min+6
                if _bootstrap_headroom_ok
                else _mode_min_support+10
            )
            support_score=float(np.clip(
                dynamic_gap_support/max(1.0,float(_support_den)),
                0.0,1.0
            ))
            margin=float(
                dynamic_gap_remaining-dynamic_gap_required_eta
            )
            margin_score=float(np.clip(
                (margin-self.dynamic_gap_min_margin+.12)/.55,
                0.0,1.0
            ))
            recent_score=float(np.clip(
                dynamic_gap_recent_support/12.0,0.0,1.0
            ))
            stability_score=float(np.clip(
                1.0-float(live_motion_profile.get('gap_cv',0.0))/1.4,
                0.0,1.0
            ))
            dynamic_gap_confidence=float(np.clip(
                .28*support_score
                + .30*margin_score
                + .20*float(vis.get('score',0.0))
                + .12*recent_score
                + .10*stability_score,
                0.0,1.0
            ))
            _mode_min_conf=float(self.mode_gap_min_confidence.get(
                difficulty_mode,self.dynamic_gap_min_confidence
            ))
            if _bootstrap_headroom_ok:
                _mode_min_conf=min(
                    .92,
                    _mode_min_conf+self.dynamic_gap_bootstrap_confidence_add
                )
            if dynamic_gap_confidence >= _mode_min_conf:
                dynamic_gap_eta=float(dynamic_gap_remaining)
                dynamic_gap_ready=True

        # Backward-compatible diagnostics for old CSV readers.
        gap_open_eta=dynamic_gap_eta
        gap_open_remaining=dynamic_gap_remaining
        gap_open_required_eta=dynamic_gap_required_eta
        gap_open_confidence=dynamic_gap_confidence
        gap_open_ready=dynamic_gap_ready
        gap_open_support=dynamic_gap_support
        gap_p25=live_motion_profile.get('p25')

        # Pattern lower-bound remaining uses P25 rather than the median.
        pattern_p25_remaining = None
        if p1.get('ready') and p1.get('p25_gap') is not None and p1.get('elapsed') is not None:
            pattern_p25_remaining = float(p1['p25_gap']) - float(p1['elapsed'])

        pattern_guard_ok = bool(
            p1.get('ready')
            and int(p1.get('support', 0)) >= self.pattern_guard_min_support
            and p1.get('p25_gap') is not None
            and float(p1.get('p25_gap')) >= self.pattern_guard_min_p25
            and float(p1.get('p_next_fast', 1.0)) <= self.pattern_guard_max_fast
        )

        # ETA source fusion:
        # visible geometry is strongest. CZN is not trusted blindly; when a
        # pattern lower bound predicts an earlier arrival, use the earlier ETA.
        if slow_window.get('ok'):
            effective_eta = float(slow_window['eta'])
            eta_source = str(slow_window['mode'])
            threat_id = slow_window.get('anchor_id')
            safe = max(
                0.0,float(effective_eta)
                - float(slow_window['required_eta'])
            )
            if eta_source == 'slow-after':
                risk = min(float(risk),8.0)
        elif direct_eta is not None:
            effective_eta = direct_eta
            eta_source = 'visible'
        elif motion_slow_eta is not None:
            effective_eta = float(motion_slow_eta)
            eta_source = 'confirmed-slow-after'
            risk = min(float(risk),8.0)
            safe = max(
                0.0,float(effective_eta)-motion_slow_required_eta
            )
        elif dynamic_gap_eta is not None:
            effective_eta = float(dynamic_gap_eta)
            eta_source = 'dynamic-gap'
            # The source already requires an empty motion corridor and no
            # visible/uncertain vehicle. Keep risk responsive but low enough to
            # let the source-specific gate decide.
            risk = min(float(risk),12.0)
            safe = max(
                0.0,float(effective_eta)-float(gap_open_required_eta)
            )
        elif clear_zone_eta is not None:
            effective_eta = max(0.0, float(clear_zone_eta))
            eta_source = 'clear-zone'
            if (
                pattern_p25_remaining is not None
                and 0.0 < pattern_p25_remaining < effective_eta
            ):
                effective_eta = pattern_p25_remaining
                eta_source = 'fused'
        elif pattern_eta is not None:
            effective_eta = pattern_eta
            eta_source = 'pattern'
        else:
            effective_eta = None
            eta_source = 'unknown'

        current_pattern_stats = learner.current_segment_speed_pattern_stats(
            lane_key, p1.get('sequence', '-')
        )

        source_rel = learner.green_source_reliability(
            eta_source, lane=lane_key
        )
        source_reliability_ok = bool(
            source_rel['attempts'] < 8 or source_rel['rate'] >= .80
        )

        decision_visible_threat = bool(l1.get('visible_threat',False))
        adaptive_direct_risk = float(l1.get('direct_risk',risk))
        if eta_source == 'slow-after' and slow_window.get('departing_anchor_safe',False):
            decision_visible_threat = False
            adaptive_direct_risk = min(adaptive_direct_risk,6.0)

        adaptive = self.adaptive.assess(
            now=wall_now,
            eta_source=eta_source,
            eta=effective_eta,
            direct_risk=adaptive_direct_risk,
            overall_risk=float(risk),
            visibility_ok=bool(vis['ok']),
            visibility_score=float(vis['score']),
            visible_threat=decision_visible_threat,
            clear_dwell=float(clear_dwell),
            recent_threat_age=float(recent_threat_age),
            pattern=p1,
            chicken_conf=float(chicken.get('confidence', 0.0)),
            traffic=traffic,
            source_reliability=float(source_rel['rate']),
            jump_time=self.jump_time,
            safety_buffer=self.safety,
        )

        live_context = {
            'lane': int(lane_key), 'source': str(eta_source),
            'eta': float(effective_eta or 0.0), 'raw_risk': float(risk),
            'motion_ratio': float(motion_view.get('ratio',1.0)),
            'motion_dwell': float(motion_clear_dwell),
            'clear_dwell': float(clear_dwell),
            'czn_speed': float(czn_ctx.get('speed_reference',0.0)),
            'adaptive_conf': float(adaptive.get('confidence',0.0)),
            'gap25': float(traffic.get('gap_p25',1.25)),
            'fast_frac': float(traffic.get('fast_fraction',.33)),
            'pattern_p25': float(current_pattern_stats.get('p25_gap') or 0.0),
            'pattern_fast': float(current_pattern_stats.get('p_next_fast',1.0)),
            'uncertain': float(l1.get('uncertain_incoming_count',0)),
            'stage_score': float(live_stage_score),
        }
        crash_memory = learner.crash_memory_score(live_context)

        green_evidence_ok = bool(adaptive['green_ok'])
        green_evidence_reason = adaptive['reason']
        stage_score = float(live_stage_score)
        memory_score = float(crash_memory.get('score',0.0))
        green_required_eta = float(
            adaptive['required_eta']
            + self.stage_eta_adjust_max*stage_score
            + .08*memory_score
        )
        source_failure_eta_floor = 0.0
        source_reliability_eta_penalty = 0.0
        czn_context_only = bool(
            eta_source in ('clear-zone','fused')
            and dynamic_gap_support
                >= self.czn_context_only_after_gap_support
        )
        if eta_source in ('clear-zone','fused') and not czn_context_only:
            source_failure_eta_floor = learner.source_failure_eta_floor(
                eta_source, lane=lane_key,
                base=max(
                    self.precision_czn_min_eta,
                    self.czn_postfix_min_eta
                )
            )
            source_reliability_eta_penalty = float(np.clip(
                (.75-float(source_rel.get('rate',.8))) / .40,
                0.0,1.0
            )) * self.czn_reliability_eta_penalty_max
            green_required_eta = max(
                green_required_eta,
                source_failure_eta_floor + source_reliability_eta_penalty
            )
        slow_window_required_eta = None
        if eta_source in ('slow-before','slow-after'):
            slow_window_required_eta = float(
                slow_window.get(
                    'required_eta',self.jump_time+self.safety+.12
                ) + .05*memory_score
            )
            green_required_eta = slow_window_required_eta
        elif eta_source == 'confirmed-slow-after':
            slow_window_required_eta = float(
                motion_slow_required_eta + .05*memory_score
            )
            # Outcome-grounded learning for the NEW confirmed source. If a
            # confirmed slow-after signal later crashes, do not repeat the same
            # remaining ETA indefinitely.
            confirmed_slow_failure_floor = learner.source_failure_eta_floor(
                eta_source,
                lane=None,
                base=self.motion_slow_min_required_eta
            )
            confirmed_slow_rel = learner.green_source_reliability(
                eta_source, lane=None
            )
            confirmed_slow_rel_penalty = float(np.clip(
                (.75-float(confirmed_slow_rel.get('rate',.8))) / .40,
                0.0,1.0
            )) * .16
            green_required_eta = max(
                slow_window_required_eta,
                float(confirmed_slow_failure_floor)
                    + confirmed_slow_rel_penalty
            )

        if eta_source == 'dynamic-gap':
            dynamic_gap_failure_floor = learner.source_failure_eta_floor(
                'dynamic-gap', lane=None,
                base=float(dynamic_gap_required_eta)
            )
            dynamic_gap_rel = learner.green_source_reliability(
                'dynamic-gap', lane=None
            )
            dynamic_gap_rel_penalty=float(np.clip(
                (.75-float(dynamic_gap_rel.get(
                    'global_rate',dynamic_gap_rel.get('rate',.8)
                )))/.45,
                0.0,1.0
            ))*self.dynamic_gap_failure_penalty_max

            safe_sim=float(crash_memory.get('safe_similarity',0.0))
            crash_sim=float(crash_memory.get('crash_similarity',0.0))
            experience_adjust=float(np.clip(
                .18*crash_sim - .08*safe_sim,
                -.08,.20
            ))
            recent_source_failures=int(
                adaptive.get('recent_source_failures',0) or 0
            )
            dynamic_gap_effective_failure_floor=(
                self._effective_dynamic_gap_failure_floor(
                    dynamic_gap_failure_floor,
                    dynamic_gap_required_eta,
                    recent_source_failures
                )
            )
            green_required_eta=max(
                float(dynamic_gap_required_eta)+experience_adjust,
                float(dynamic_gap_effective_failure_floor)
                    + dynamic_gap_rel_penalty
            )
            gap_open_failure_floor=float(dynamic_gap_effective_failure_floor)
            gap_open_rel=dynamic_gap_rel
        else:
            dynamic_gap_failure_floor = 0.0
            dynamic_gap_effective_failure_floor = 0.0
            dynamic_gap_rel = {
                'rate':1.0,'global_rate':1.0,
                'attempts':0,'global_attempts':0
            }
            gap_open_failure_floor = 0.0
            gap_open_rel = dynamic_gap_rel

        # V4.2.2 HARD calibration vetoes.
        # A large CZN ETA is NOT evidence of safety while current-session speed
        # calibration is immature.
        if eta_source in ('clear-zone', 'fused'):
            if not czn_ctx['calibrated']:
                green_evidence_ok = False
                green_evidence_reason = (
                    f"CZN CAL E{czn_ctx['confirmed_events']}/"
                    f"{czn_ctx['required_events']} "
                    f"R{czn_ctx['unique_raw_tracks']}/"
                    f"{czn_ctx['required_unique_tracks']}"
                )

        if czn_context_only:
            green_required_eta=float(dynamic_gap_required_eta)
            green_evidence_ok=False
            if not motion_view.get('clear',False):
                green_evidence_reason='DG WAIT VEHICLE PASS'
            elif float(current_clear_elapsed) > self.dynamic_gap_max_elapsed:
                green_evidence_reason='DG WAIT NEXT GAP'
            else:
                green_evidence_reason='DG BUILDING HORIZON'

        # Historical pattern timing is also not allowed to be the sole GREEN
        # source immediately after a reset. It must observe a few clean current
        # segment vehicles first.
        if eta_source == 'pattern':
            if len(segment_events_all) < self.pattern_green_min_segment_events:
                green_evidence_ok = False
                green_evidence_reason = (
                    f"PAT CAL {len(segment_events_all)}/"
                    f"{self.pattern_green_min_segment_events}"
                )

        # V4.2.4 precision-first hard vetoes. False negatives are preferred
        # over false GREENs.
        if self.precision_mode:
            session_age = float(czn_ctx.get('warmup_age', 0.0))
            post_crash_age = max(0.0, wall_now - self._last_crash_at)

            if post_crash_age < self.post_crash_hold_seconds:
                green_evidence_ok = False
                green_evidence_reason = (
                    f"RESPAWN HOLD {post_crash_age:.1f}/"
                    f"{self.post_crash_hold_seconds:.1f}s"
                )

            elif l1.get('uncertain_incoming_count', 0) > 0:
                green_evidence_ok = False
                green_evidence_reason = (
                    f"UNCERTAIN VEHICLE {l1.get('uncertain_incoming_count',0)}"
                )

            elif eta_source in ('clear-zone', 'fused'):
                # V4.2.6: CZN is usable again only when TWO independent systems
                # agree the incoming corridor is empty:
                #   (1) no tracked/uncertain vehicle,
                #   (2) raw MOG2 foreground mask remains clear.
                if not self.precision_allow_czn_green:
                    green_evidence_ok = False
                    green_evidence_reason = 'CZN DISABLED'

                elif not czn_ctx.get('calibrated', False):
                    green_evidence_ok = False
                    green_evidence_reason = 'CZN NOT CALIBRATED'

                elif (
                    str(czn_ctx.get('calibration_mode','WAIT')) == 'PRIOR'
                    and not (
                        int(czn_ctx.get('confirmed_events',0))
                            >= self.czn_live_min_confirmed
                        or (
                            int(czn_ctx.get('unique_raw_tracks',0))
                                >= self.czn_live_min_raw_tracks
                            and int(czn_ctx.get('raw_samples',0))
                                >= self.czn_live_min_raw_samples
                        )
                        or bool(
                            live_motion_profile.get(
                                'motion_live_ready',False
                            )
                        )
                    )
                ):
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"CZN LIVE E{int(czn_ctx.get('confirmed_events',0))}/"
                        f"{self.czn_live_min_confirmed} "
                        f"R{int(czn_ctx.get('unique_raw_tracks',0))}/"
                        f"{self.czn_live_min_raw_tracks} "
                        f"G{int(live_motion_profile.get('support',0))}/"
                        f"{self.motion_live_min_gap_support}"
                    )

                # Once CZN is calibrated, do not
                # re-block it merely because the recent rolling event window
                # temporarily contains <N crossings. V4.3.5 spent most of the
                # run stuck at STAGE OBS 0/4 despite czn_calibrated=1.
                elif not motion_view.get('available', False):
                    green_evidence_ok = False
                    green_evidence_reason = 'CZN MOTION MASK WAIT'

                elif not motion_view.get('clear', False):
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"CZN MOTION {100*motion_view.get('ratio',1):.1f}%"
                    )

                elif motion_clear_dwell < (
                    self.precision_czn_motion_clear_dwell
                    + self.stage_motion_dwell_adjust_max*stage_score
                    + .20*memory_score
                ):
                    req_motion_dwell = (
                        self.precision_czn_motion_clear_dwell
                        + self.stage_motion_dwell_adjust_max*stage_score
                        + .20*memory_score
                    )
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"CZN MOT DWELL {motion_clear_dwell:.1f}/{req_motion_dwell:.1f}"
                    )

                elif float(clear_dwell) < (
                    self.precision_czn_min_clear_dwell
                    + self.stage_clear_dwell_adjust_max*stage_score
                    + .25*memory_score
                ):
                    req_clear_dwell = (
                        self.precision_czn_min_clear_dwell
                        + self.stage_clear_dwell_adjust_max*stage_score
                        + .25*memory_score
                    )
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"CZN DWELL {float(clear_dwell):.1f}/{req_clear_dwell:.1f}"
                    )

                elif float(vis.get('score', 0.0)) < self.precision_czn_visibility_min:
                    green_evidence_ok = False
                    green_evidence_reason = 'CZN VISIBILITY LOW'

                elif float(recent_threat_age) < self.precision_czn_recent_threat_age:
                    green_evidence_ok = False
                    green_evidence_reason = 'CZN RECENT THREAT'

                elif effective_eta is None or float(effective_eta) < float(green_required_eta):
                    req_eta = float(green_required_eta)
                    green_evidence_ok = False
                    tag = 'CZN FAIL-FLOOR' if source_failure_eta_floor > self.precision_czn_min_eta+.02 else 'CZN ETA'
                    green_evidence_reason = (
                        f"{tag} {0.0 if effective_eta is None else float(effective_eta):.2f}"
                        f"<{req_eta:.2f}"
                    )

                elif float(adaptive.get('confidence', 0.0)) < (
                    self.precision_czn_min_conf
                    + self.stage_conf_adjust_max*stage_score
                    + .03*memory_score
                ):
                    req_conf = (
                        self.precision_czn_min_conf
                        + self.stage_conf_adjust_max*stage_score
                        + .03*memory_score
                    )
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"CZN CONF {int(100*float(adaptive.get('confidence',0)))}"
                        f"<{int(100*req_conf)}"
                    )

                elif (
                    int(current_pattern_stats.get('support', 0)) > 0
                    and (
                        (
                            current_pattern_stats.get('p25_gap') is not None
                            and float(current_pattern_stats.get('p25_gap'))
                                < self.precision_czn_bad_pattern_p25
                        )
                        or float(current_pattern_stats.get('p_next_fast', 0.0))
                            > self.precision_czn_bad_pattern_fast
                    )
                ):
                    green_evidence_ok = False
                    green_evidence_reason = 'CZN PATTERN CAUTION'

                # Source reliability is expressed as extra ETA margin above.
                # Do not permanently quarantine a screen-local lane number; the
                # same lane ID is reused after viewport panning/progression.

            elif eta_source == 'dynamic-gap':
                if not motion_view.get('available',False):
                    green_evidence_ok=False
                    green_evidence_reason='DG MOTION WAIT'
                elif not motion_view.get('clear',False):
                    green_evidence_ok=False
                    green_evidence_reason='DG MOTION BUSY'
                elif dynamic_gap_support < self.dynamic_gap_min_support:
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"DG SUPPORT {dynamic_gap_support}/"
                        f"{self.dynamic_gap_min_support}"
                    )
                elif gap_preceding_busy is None:
                    green_evidence_ok=False
                    green_evidence_reason='DG WAIT PASS'
                elif float(gap_preceding_busy) > self.dynamic_gap_max_preceding_busy:
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"DG BUSY {float(gap_preceding_busy):.2f}>"
                        f"{self.dynamic_gap_max_preceding_busy:.2f}"
                    )
                elif float(motion_view.get('mog_global_ratio',0.0)) > self.dynamic_gap_max_mog_ratio:
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"DG MOG {100.0*float(motion_view.get('mog_global_ratio',0.0)):.0f}%"
                    )
                elif not (
                    self.dynamic_gap_min_elapsed
                    <= float(current_clear_elapsed)
                    <= self.dynamic_gap_max_elapsed
                ):
                    green_evidence_ok=False
                    green_evidence_reason='DG PHASE'
                elif dynamic_gap_remaining is None:
                    green_evidence_ok=False
                    green_evidence_reason='DG HORIZON UNKNOWN'
                elif (
                    dynamic_gap_action_lease is None
                    or float(dynamic_gap_action_lease)
                        < float(dynamic_gap_lease_required)
                ):
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"DG LEASE {0.0 if dynamic_gap_action_lease is None else float(dynamic_gap_action_lease):.2f}"
                        f"<{float(dynamic_gap_lease_required):.2f}"
                    )
                elif float(dynamic_gap_remaining) < float(green_required_eta):
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"DG REM {float(dynamic_gap_remaining):.2f}"
                        f"<{float(green_required_eta):.2f}"
                    )
                elif float(vis.get('score',0.0)) < self.dynamic_gap_min_visibility:
                    green_evidence_ok=False
                    green_evidence_reason='DG VIS LOW'
                elif int(l1.get('uncertain_incoming_count',0)) > 0:
                    green_evidence_ok=False
                    green_evidence_reason='DG UNCERTAIN VEHICLE'
                elif bool(l1.get('visible_threat',False)):
                    green_evidence_ok=False
                    green_evidence_reason='DG VISIBLE THREAT'
                elif float(dynamic_gap_confidence) < self.dynamic_gap_min_confidence:
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"DG CONF {int(100*dynamic_gap_confidence)}"
                    )
                else:
                    green_evidence_ok=True
                    green_evidence_reason=''

            elif eta_source == 'confirmed-slow-after':
                confirmed_rel=learner.green_source_reliability(
                    'confirmed-slow-after', lane=None
                )
                src_attempts=int(
                    confirmed_rel.get('global_attempts',
                                      confirmed_rel.get('attempts',0))
                )
                src_rate=float(
                    confirmed_rel.get('global_rate',
                                      confirmed_rel.get('rate',1.0))
                )
                support_score=min(
                    1.0,
                    float(slow_motion_support)
                    / max(
                        1.0,
                        float(self.motion_slow_min_support+4)
                    )
                )
                gap_score=float(np.clip(
                    (
                        float(slow_motion_p25 or 0.0)
                        - motion_slow_required_eta
                    )/.70,0.0,1.0
                ))
                eta_margin=(
                    float(effective_eta or 0.0)
                    - float(green_required_eta)
                )
                margin_score=float(
                    np.clip((eta_margin+.20)/.50,0.0,1.0)
                )
                motion_slow_conf=float(np.clip(
                    .30*support_score
                    + .25*gap_score
                    + .25*margin_score
                    + .20*float(vis.get('score',0.0)),
                    0.0,1.0
                ))

                if not motion_view.get('available',False):
                    green_evidence_ok=False
                    green_evidence_reason='CSA MOTION WAIT'
                elif not motion_view.get('clear',False):
                    green_evidence_ok=False
                    green_evidence_reason='CSA MOTION BUSY'
                elif preceding_busy is None:
                    green_evidence_ok=False
                    green_evidence_reason='CSA NO RAW ANCHOR'
                elif (
                    self.motion_slow_require_confirmed_event
                    and not motion_slow_anchor_ok
                ):
                    green_evidence_ok=False
                    green_evidence_reason='CSA NO CONFIRMED SLOW'
                elif slow_motion_support < self.motion_slow_min_support:
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"CSA SUPPORT {slow_motion_support}/"
                        f"{self.motion_slow_min_support}"
                    )
                elif (
                    slow_motion_p25 is None
                    or float(slow_motion_p25)
                        < self.motion_slow_min_p25
                ):
                    green_evidence_ok=False
                    green_evidence_reason='CSA GAP WEAK'
                elif (
                    current_clear_elapsed
                    < self.motion_slow_min_clear_dwell
                ):
                    green_evidence_ok=False
                    green_evidence_reason='CSA VERIFY'
                elif (
                    effective_eta is None
                    or float(effective_eta)
                        < float(green_required_eta)
                ):
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"CSA ETA "
                        f"{0.0 if effective_eta is None else float(effective_eta):.2f}"
                        f"<{float(green_required_eta):.2f}"
                    )
                elif motion_slow_conf < .68:
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"CSA CONF {int(100*motion_slow_conf)}<68"
                    )
                elif (
                    src_attempts >= 3
                    and src_rate
                        < self.motion_slow_source_min_reliability
                ):
                    green_evidence_ok=False
                    green_evidence_reason='CSA SOURCE REL LOW'
                else:
                    green_evidence_ok=True
                    green_evidence_reason=''

            elif eta_source in ('slow-before','slow-after'):
                profile_conf=float(slow_window.get('profile_confidence',0.0))
                sw_eta=slow_window.get('eta')
                req_eta=float(slow_window_required_eta or 0.0)
                slow_combined_conf=float(np.clip(
                    .46*profile_conf
                    + .28*float(vis.get('score',0.0))
                    + .26*np.clip((float(sw_eta or 0.0)-req_eta+.35)/.70,0.0,1.0),
                    0.0,1.0
                ))
                slow_window['combined_confidence']=slow_combined_conf

                if not slow_window.get('profile_ok',False):
                    green_evidence_ok=False
                    green_evidence_reason='SLOW PROFILE WEAK'
                elif not vis.get('ok',False):
                    green_evidence_ok=False
                    green_evidence_reason='SLOW VISIBILITY LOW'
                elif int(l1.get('uncertain_incoming_count',0))>0:
                    green_evidence_ok=False
                    green_evidence_reason='SLOW UNCERTAIN VEHICLE'
                elif sw_eta is None or float(sw_eta)<req_eta:
                    green_evidence_ok=False
                    green_evidence_reason=(
                        f"SLOW ETA {0.0 if sw_eta is None else float(sw_eta):.2f}"
                        f"<{req_eta:.2f}"
                    )
                elif slow_combined_conf < .70:
                    green_evidence_ok=False
                    green_evidence_reason=f"SLOW CONF {int(100*slow_combined_conf)}<70"
                elif (
                    int(source_rel.get('global_attempts',source_rel.get('attempts',0)))>=4
                    and float(source_rel.get('global_rate',source_rel.get('rate',1.0)))
                        < self.slow_window_source_min_reliability
                    and float(sw_eta or 0.0) < req_eta + .18
                ):
                    green_evidence_ok=False
                    green_evidence_reason='SLOW SOURCE NEEDS EXTRA ETA'
                else:
                    green_evidence_ok=True
                    green_evidence_reason=''

            elif eta_source == 'visible':
                if effective_eta is None or float(effective_eta) < self.precision_visible_eta:
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"PREC ETA {0.0 if effective_eta is None else float(effective_eta):.2f}"
                        f"<{self.precision_visible_eta:.2f}"
                    )
                elif float(adaptive.get('confidence', 0.0)) < self.precision_min_conf:
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"PREC CONF {int(100*float(adaptive.get('confidence',0)))}"
                        f"<{int(100*self.precision_min_conf)}"
                    )

            elif eta_source == 'pattern':
                pp25 = p1.get('p25_gap')
                if len(segment_events_all) < self.precision_min_global_events:
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"PAT OBS {len(segment_events_all)}/"
                        f"{self.precision_min_global_events}"
                    )
                elif int(p1.get('support', 0)) < self.precision_pattern_support:
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"PAT SUP {int(p1.get('support',0))}/"
                        f"{self.precision_pattern_support}"
                    )
                elif int(current_pattern_stats.get('support',0)) < self.precision_current_pattern_support:
                    green_evidence_ok = False
                    green_evidence_reason = (
                        f"CUR PAT {int(current_pattern_stats.get('support',0))}/"
                        f"{self.precision_current_pattern_support}"
                    )
                elif (
                    current_pattern_stats.get('p25_gap') is None
                    or float(current_pattern_stats.get('p25_gap')) < self.precision_current_pattern_p25
                ):
                    green_evidence_ok = False
                    green_evidence_reason = 'CUR PAT GAP LOW'
                elif float(current_pattern_stats.get('p_next_fast',1.0)) > self.precision_current_pattern_max_fast:
                    green_evidence_ok = False
                    green_evidence_reason = 'CUR PAT NEXT FAST'
                elif float(p1.get('confidence', 0.0)) < self.precision_pattern_conf:
                    green_evidence_ok = False
                    green_evidence_reason = 'PAT CONF LOW'
                elif pp25 is None or float(pp25) < self.precision_pattern_p25:
                    green_evidence_ok = False
                    green_evidence_reason = 'PAT GAP LOW'
                elif float(p1.get('p_next_fast', 1.0)) > self.precision_pattern_max_fast:
                    green_evidence_ok = False
                    green_evidence_reason = 'PAT NEXT FAST'
                elif effective_eta is None or float(effective_eta) < self.precision_pattern_eta:
                    green_evidence_ok = False
                    green_evidence_reason = 'PAT ETA LOW'

            else:
                green_evidence_ok = False
                green_evidence_reason = 'PRECISION: ETA SOURCE UNKNOWN'

        # Crash memory becomes a hard blocker only after repeated similar
        # failures. A single old crash increases requirements but does not
        # permanently blacklist a physically verified immediate-lane gap.
        repeated_crash_match = int(crash_memory.get('matches',0))
        if memory_score >= self.crash_memory_block_score and repeated_crash_match >= 2:
            green_evidence_ok = False
            green_evidence_reason = f"REPEATED CRASH {int(100*memory_score)}%"

        verified_gap = bool(
            czn_ctx.get('calibrated',False)
            and vis.get('ok',False)
            and motion_view.get('available',False)
            and motion_view.get('clear',False)
            and int(l1.get('uncertain_incoming_count',0)) == 0
            and not bool(l1.get('visible_threat',False))
            and float(motion_clear_dwell) >= float(self.precision_czn_motion_clear_dwell)
            and float(clear_dwell) >= float(self.precision_czn_min_clear_dwell)
            and effective_eta is not None
            and float(effective_eta) >= float(green_required_eta)
        )
        if verified_gap and green_evidence_reason.startswith(('PAT ','STAGE OBS','CZN LANE OBS')):
            green_evidence_ok = True
            green_evidence_reason = ''

        seq1 = p1.get('sequence', '-')
        tpat = l1.get('type_pattern') or {}
        tseq = tpat.get('sequence','-')
        pattern_text = f'SPD {seq1} | TYP {tseq}'
        return {
            'risk': float(np.clip(risk, 2, 99)),
            'action_reason': 'single-lane learning and GREEN; TOP to BOTTOM (+Y)',
            'lane1': l1, 'lane2': l2,
            'two_lane_learning': bool(l2 is not None),
            'lookahead_lane': '-' if l2 is None else int(l2['lane']),
            'lookahead_risk': 0.0 if l2 is None else float(l2.get('risk',0.0)),
            'lookahead_candidate_count': 0 if l2 is None else int(l2.get('candidate_count',0)),
            'lookahead_visible_threat': False if l2 is None else bool(l2.get('visible_threat',False)),
            'lookahead_clear_dwell': 0.0 if l2_context is None else float(l2_context.get('clear_dwell',0.0)),
            'lookahead_motion_clear_dwell': 0.0 if l2_context is None else float(l2_context.get('motion_clear_dwell',0.0)),
            'lookahead_motion_ratio': 1.0 if l2_context is None else float(l2_context.get('motion_ratio',1.0)),
            'lookahead_stage_difficulty': 0.0 if stage2_profile is None else float(stage2_profile.get('difficulty',0.0)),
            'lookahead_stage_speed_p95': 0.0 if stage2_profile is None else float(stage2_profile.get('speed_p95',0.0)),
            # V5.2.9: preserve the real one-lane geometry for outcome learning.
            # Earlier builds clipped this to 320 px, while this game layout often
            # uses ~400-480 px lane spacing. That made real successful jumps fall
            # outside the GREEN success envelope and become UNKNOWN. Target
            # geometry has already been validated upstream, so only keep a broad
            # pathological upper bound here.
            'next_lane_distance': float(
                max(80.0, min(700.0, abs(float(l1['lane_x']) - float(chicken['cx']))))
            ),
            'precision_mode': bool(self.precision_mode),
            'precision_czn_green_allowed': bool(self.precision_allow_czn_green),
            'precision_lane_events': int(len(segment_lane_events)),
            'precision_global_events': int(len(segment_events_all)),
            'stage_difficulty_score': float(live_stage_score),
            'lane_history_difficulty_score': float(stage_profile.get('difficulty',0.0)),
            'live_traffic_difficulty_score': float(live_stage_score),
            'live_speed_difficulty_score': float(live_speed_score),
            'live_density_difficulty_score': float(live_density_score),
            'motion_gap_support': int(live_motion_profile.get('support',0)),
            'gap_open_eta': gap_open_eta,
            'gap_open_required_eta': (
                float(green_required_eta) if eta_source=='gap-open'
                else float(gap_open_required_eta)
            ),
            'gap_open_remaining': gap_open_remaining,
            'gap_open_support': int(gap_open_support),
            'gap_open_confidence': float(gap_open_confidence),
            'gap_open_ready': bool(gap_open_ready),
            'gap_open_failure_floor': float(gap_open_failure_floor),
            'gap_open_source_rate': float(
                gap_open_rel.get('global_rate',gap_open_rel.get('rate',1.0))
            ),
            'dynamic_gap_ready': bool(dynamic_gap_ready),
            'dynamic_gap_cycle_id': int(live_motion_profile.get('cycle_id',0)),
            'dynamic_gap_quantile': float(dynamic_gap_quantile),
            'dynamic_gap_unlatched_lower_bound': dynamic_gap_unlatched_lower_bound,
            'dynamic_gap_lower_bound': (
                None if dynamic_gap_lower_bound is None
                else float(dynamic_gap_lower_bound)
            ),
            'dynamic_gap_recent_support': int(dynamic_gap_recent_support),
            'dynamic_gap_session_prior_support': int(prior_support),
            'dynamic_gap_session_prior_lower_bound': prior_lower,
            'dynamic_gap_bootstrap_candidate': int(bool(dynamic_gap_bootstrap_candidate)),
            'dynamic_gap_bootstrap_active': int(bool(
                dynamic_gap_bootstrap_candidate
                and dynamic_gap_bootstrap_lower is not None
                and dynamic_gap_bootstrap_lower
                    >= dynamic_gap_required_eta
                        + self.dynamic_gap_bootstrap_min_margin
            )),
            'dynamic_gap_bootstrap_lower_bound': dynamic_gap_bootstrap_lower,
            'dynamic_gap_bootstrap_min_local_support': int(_bootstrap_local_min),
            'dynamic_gap_required_eta': float(dynamic_gap_required_eta),
            'dynamic_gap_remaining': (
                None if dynamic_gap_remaining is None
                else float(dynamic_gap_remaining)
            ),
            'dynamic_gap_confidence': float(dynamic_gap_confidence),
            'dynamic_gap_mode_min_support': int(self.mode_gap_min_support.get(difficulty_mode,self.dynamic_gap_min_support)),
            'dynamic_gap_mode_min_confidence': float(self.mode_gap_min_confidence.get(difficulty_mode,self.dynamic_gap_min_confidence)),
            'dynamic_gap_mode_max_elapsed': float(self.mode_gap_max_elapsed.get(difficulty_mode,self.dynamic_gap_max_elapsed)),
            'dynamic_gap_recent_lower_bound': None if recent_lower is None else float(recent_lower),
            'dynamic_gap_long_lower_bound': None if long_lower is None else float(long_lower),
            'dynamic_gap_recent_weight': float(dynamic_gap_recent_weight),
            'dynamic_gap_regime_direction': str(dynamic_gap_regime_direction),
            'dynamic_gap_failure_floor': float(dynamic_gap_failure_floor),
            'dynamic_gap_effective_failure_floor': float(
                dynamic_gap_effective_failure_floor
            ),
            'dynamic_gap_difficulty_credit': float(
                dynamic_gap_difficulty_credit
            ),
            'dynamic_gap_source_rate': float(
                dynamic_gap_rel.get(
                    'global_rate',dynamic_gap_rel.get('rate',1.0)
                )
            ),
            'dynamic_gap_pipeline_latency': float(measured_pipeline),
            'dynamic_gap_reaction_budget': float(
                dynamic_gap_reaction_budget
            ),
            'dynamic_gap_observed_action_delay': float(
                dynamic_gap_observed_action_delay
            ),
            'dynamic_gap_action_lease': (
                None if dynamic_gap_action_lease is None
                else float(dynamic_gap_action_lease)
            ),
            'dynamic_gap_lease_required': float(
                dynamic_gap_lease_required
            ),
            'dynamic_gap_effective_clear_elapsed': float(
                dynamic_gap_effective_clear_elapsed
            ),
            'dynamic_gap_czn_capped': bool(
                upstream_clear_eta is not None
                and dynamic_gap_support
                    <= self.dynamic_gap_czn_cap_max_support
            ),
            'czn_context_only': bool(czn_context_only),
            'motion_gap_p25': live_motion_profile.get('p25'),
            'motion_gap_median': live_motion_profile.get('median'),
            'motion_busy_fraction': float(
                live_motion_profile.get('busy_fraction',0.0)
            ),
            'motion_live_ready': bool(
                live_motion_profile.get('motion_live_ready',False)
            ),
            'motion_current_clear_elapsed': float(
                live_motion_profile.get('current_clear_elapsed',0.0)
            ),
            'dynamic_gap_mog_global_ratio': float(
                motion_view.get('mog_global_ratio',0.0)
            ),
            'dynamic_gap_preceding_busy_ok': int(
                gap_preceding_busy is not None
                and float(gap_preceding_busy) <= self.dynamic_gap_max_preceding_busy
            ),
            'dynamic_gap_slow_guard': int(approaching_slow_guard),
            'motion_preceding_busy_duration': (
                None
                if live_motion_profile.get(
                    'preceding_busy_duration'
                ) is None
                else float(
                    live_motion_profile.get(
                        'preceding_busy_duration'
                    )
                )
            ),
            'motion_slow_support': int(
                live_motion_profile.get('slow_support',0)
            ),
            'motion_slow_p25': live_motion_profile.get('slow_p25'),
            'motion_slow_median': live_motion_profile.get(
                'slow_median'
            ),
            'motion_slow_eta': motion_slow_eta,
            'motion_slow_required_eta': (
                motion_slow_required_eta
                if eta_source=='confirmed-slow-after' else None
            ),
            'motion_slow_anchor_ok': bool(motion_slow_anchor_ok),
            'motion_slow_anchor_age': motion_slow_anchor_age,
            'motion_slow_anchor_alignment': motion_slow_anchor_alignment,
            'motion_slow_anchor_id': motion_slow_anchor_id,
            'confirmed_slow_failure_floor': (
                float(confirmed_slow_failure_floor)
                if eta_source=='confirmed-slow-after' else 0.0
            ),
            'source_failure_eta_floor': float(source_failure_eta_floor),
            'source_reliability_eta_penalty': float(source_reliability_eta_penalty),
            'czn_live_ready': bool(
                int(czn_ctx.get('confirmed_events',0))
                    >= self.czn_live_min_confirmed
                or (
                    int(czn_ctx.get('unique_raw_tracks',0))
                        >= self.czn_live_min_raw_tracks
                    and int(czn_ctx.get('raw_samples',0))
                        >= self.czn_live_min_raw_samples
                )
                or bool(
                    live_motion_profile.get(
                        'motion_live_ready',False
                    )
                )
            ),
            'stage_profile_support': int(stage_profile.get('support',0)),
            'stage_speed_p95': float(stage_profile.get('speed_p95',0.0)),
            'stage_gap_p25': float(stage_profile.get('gap_p25',0.0)),
            'stage_speed_reference': float(stage_profile.get('speed_reference',0.0)),
            'crash_memory_score': float(memory_score),
            'crash_memory_matches': int(crash_memory.get('matches',0)),
            'crash_memory_safe_similarity': float(crash_memory.get('safe_similarity',0.0)),
            'uncertain_incoming_count': int(l1.get('uncertain_incoming_count',0)),
            'current_pattern_support': int(current_pattern_stats.get('support',0)),
            'current_pattern_p25': current_pattern_stats.get('p25_gap'),
            'current_pattern_p_next_fast': float(current_pattern_stats.get('p_next_fast',1.0)),
            'slow_window_mode': str(slow_window.get('mode','')),
            'slow_window_profile_support': int(slow_window.get('support',0)),
            'slow_window_lane_support': int(slow_window.get('lane_support',0)),
            'slow_window_profile_source': str(slow_window.get('profile_source','none')),
            'slow_profile_recent_lane_support':slow_profile.get('recent_lane_support',0),
            'slow_profile_recent_global_support':slow_profile.get('recent_global_support',0),
            'slow_profile_class_mismatches':slow_profile.get('class_mismatches',0),
            'slow_profile_directional_active':int(_slow_context),
            'slow_window_profile_confidence': float(slow_window.get('profile_confidence',0.0)),
            'slow_window_p_fast': float(slow_window.get('p_fast',1.0)),
            'slow_window_p25_gap': slow_window.get('p25_gap'),
            'slow_window_median_gap': slow_window.get('median_gap'),
            'slow_window_eta': slow_window.get('eta'),
            'slow_window_required_eta': slow_window_required_eta,
            'slow_window_reason': str(slow_window.get('reason','')),
            'slow_window_anchor_id': slow_window.get('anchor_id'),
            'slow_window_follower_eta': slow_window.get('follower_eta'),
            'slow_window_combined_confidence': float(slow_window.get('combined_confidence',0.0)),
            'slow_after_guard_active': bool(slow_after_guard_active),
            'recent_slow_pass_age': recent_slow_pass_age,
            'motion_activity_risk': float(motion_activity_risk),
            'motion_corridor_available': bool(motion_view.get('available',False)),
            'motion_corridor_clear': bool(motion_view.get('clear',False)),
            'motion_corridor_ratio': float(motion_view.get('ratio',1.0)),
            'motion_clear_dwell': float(motion_clear_dwell),
            'safe_window': safe,
            'tti': effective_eta,
            'direct_eta': direct_eta,
            'pattern_eta': pattern_eta,
            'clear_zone_eta': clear_zone_eta,
            'clear_zone_direction': clear_zone_direction,
            'clear_zone_distance': clear_zone_distance,
            'effective_eta': effective_eta,
            'eta_source': eta_source,
            'lane_visibility_ok': bool(vis['ok']),
            'lane_visibility_score': float(vis['score']),
            'lane_mean_gray': float(vis['mean_gray']),
            'lane_dark_ratio': float(vis['dark_ratio']),
            'lane_bright_ratio': float(vis.get('bright_ratio',0.0)),
            'clear_dwell': float(clear_dwell),
            'recent_threat_age': float(recent_threat_age),
            'pattern_p25_remaining': pattern_p25_remaining,
            'pattern_guard_ok': bool(pattern_guard_ok),
            'green_evidence_ok': bool(green_evidence_ok),
            'green_evidence_reason': green_evidence_reason,
            'green_required_eta': float(green_required_eta),
            'czn_calibrated': bool(czn_ctx['calibrated']),
            'czn_confirmed_events': int(czn_ctx['confirmed_events']),
            'czn_required_events': int(czn_ctx['required_events']),
            'czn_raw_speed_samples': int(czn_ctx['raw_samples']),
            'czn_unique_raw_tracks': int(czn_ctx['unique_raw_tracks']),
            'czn_required_unique_tracks': int(czn_ctx['required_unique_tracks']),
            'czn_calibration_mode': czn_ctx['calibration_mode'],
            'czn_calibration_age': float(czn_ctx['warmup_age']),
            'czn_event_speed_p95': float(czn_ctx['event_p95']),
            'czn_raw_speed_p95': float(czn_ctx['raw_p95']),
            'czn_speed_reference': float(czn_ctx['speed_reference']),
            'czn_live_speed_reference': float(czn_ctx.get('live_speed_reference',czn_ctx['speed_reference'])),
            'czn_historical_speed_p95': czn_ctx.get('historical_speed_p95'),
            'czn_historical_prior_applied': int(bool(czn_ctx.get('historical_prior_applied',False))),
            'czn_speed_reference_source': str(czn_ctx.get('speed_reference_source','LIVE')),
            'czn_live_speed_support': int(czn_ctx.get('live_speed_support',0)),
            'czn_session_speed_support': int(czn_ctx.get('session_speed_support',0)),
            'czn_session_speed_guard_reference': float(czn_ctx.get('session_speed_guard_reference',0.0)),
            'czn_observed_clear_speed_reference': float(czn_ctx.get('observed_clear_speed_reference',czn_ctx['speed_reference'])),
            'czn_stage_speed_reference': float(czn_ctx.get('stage_speed_reference',0.0)),
            'adaptive_required_dwell': float(adaptive['required_dwell']),
            'adaptive_confidence': float(adaptive['confidence']),
            'adaptive_required_confidence': float(adaptive['required_confidence']),
            'regime_id': int(adaptive['regime_id']),
            'regime_samples': int(adaptive['regime_samples']),
            'regime_reason': adaptive['regime_reason'],
            'regime_speed_p90': float(adaptive['speed_p90']),
            'regime_gap_p25': float(adaptive['gap_p25']),
            'regime_gap_cv': float(adaptive['gap_cv']),
            'regime_fast_fraction': float(adaptive['fast_fraction']),
            'difficulty_mode': str(difficulty_mode),
            'difficulty_mode_score': float(difficulty_mode_state.get('score',0.5)),
            'difficulty_mode_raw_score': float(difficulty_mode_state.get('raw_score',0.5)),
            'difficulty_mode_candidate': str(difficulty_mode_state.get('candidate',difficulty_mode)),
            'difficulty_mode_candidate_age': float(difficulty_mode_state.get('candidate_age',0.0)),
            'difficulty_mode_age': float(difficulty_mode_state.get('age',0.0)),
            'difficulty_mode_switches': int(difficulty_mode_state.get('switches',0)),
            'difficulty_mode_reason': str(difficulty_mode_state.get('reason','')),
            'difficulty_mode_floor': str(difficulty_mode_state.get('mode_floor','EASY')),
            'difficulty_gap_score': float(difficulty_mode_state.get('gap_score',0.5)),
            'difficulty_speed_score': float(difficulty_mode_state.get('speed_score',0.5)),
            'difficulty_density_score': float(difficulty_mode_state.get('density_score',0.5)),
            'recent_regime_crashes': int(adaptive['recent_crashes']),
            'recent_green_successes': int(adaptive['recent_successes']),
            'recent_green_failures': int(adaptive['recent_failures']),
            'recent_green_reliability': float(adaptive['recent_reliability']),
            'adaptive_warmup': bool(adaptive['warmup']),
            'eta_source_reliability': float(source_rel['rate']),
            'eta_source_attempts': int(source_rel['attempts']),
            'eta_source_lane_attempts': int(source_rel.get('lane_attempts',0)),
            'eta_source_lane_rate': float(source_rel.get('lane_rate',source_rel['rate'])),
            'eta_source_global_attempts': int(source_rel.get('global_attempts',0)),
            'eta_source_global_rate': float(source_rel.get('global_rate',source_rel['rate'])),
            'threat_id': threat_id,
            'lane': int(l1['lane']),
            'lane2_id': int(l2['lane']) if l2 else None,
            'ml_samples': learner.supervised_n,
            'pattern_events': learner.pattern_event_n,
            'pattern_text': pattern_text,
            'chicken_ok': True,
            'training_features': l1.get('training_features'),
            'visible_threat': bool(decision_visible_threat),
            'ml_risk': float(l1.get('ml_risk', 2.0)),
            'chicken_x': float(chicken['cx']),
            'chicken_y': float(chicken['cy']),
        }
