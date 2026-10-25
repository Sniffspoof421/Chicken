import csv
import os
import math
import time
from pathlib import Path
from collections import deque, defaultdict, Counter
import numpy as np
import joblib
import copy
import threading
from .slow_profile import build_slow_profile
from sklearn.cluster import MiniBatchKMeans
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler


class OnlineLearner:
    """Online traffic learner for speed, appearance and recurring lane patterns.

    It learns three complementary things:
      1) slow / medium / fast speed clusters,
      2) rough recurring vehicle appearance/type clusters,
      3) sequence-conditioned gaps, e.g. F,F,F -> longer break.

    Pattern output is used only as a prior. Direct geometry always overrides it
    when a visible vehicle is on a collision course.
    """

    def __init__(self, folder, cfg):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.model_dir = self.folder.parent / 'models'
        self.model_dir.mkdir(exist_ok=True)
        self.session_started_ts = time.time()
        self.path = self.folder / f"session_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        self.rows = deque(maxlen=int(cfg.get('max_rows_per_session', 100000)))

        self.speeds = deque(maxlen=50000)
        # V2.9: speed classes are calibrated from CONFIRMED crossing events,
        # not raw motion blobs. This prevents stationary/noisy detections from
        # collapsing every traffic event into SLOW.
        self.event_speeds = deque(maxlen=int(cfg.get('speed_calibration_window', 400)))
        self.speed_min_events = int(cfg.get('speed_min_calibration_events', 12))
        self.speed_slow_percentile = float(cfg.get('speed_slow_percentile', 35))
        self.speed_fast_percentile = float(cfg.get('speed_fast_percentile', 70))
        self.speed_min_band_px_s = float(cfg.get('speed_min_band_px_s', 22))
        self.speed_fallback_slow = float(cfg.get('speed_fallback_slow_px_s', 75))
        self.speed_fallback_fast = float(cfg.get('speed_fallback_fast_px_s', 155))

        # Kept for backward-compatible saved state/type behavior, but V2.9
        # no longer uses this KMeans output to assign S/M/F event labels.
        self.cluster = MiniBatchKMeans(n_clusters=3, batch_size=64, random_state=42, n_init='auto')
        self.cluster_ready = False
        self.speed_buf = []

        self.type_cluster = MiniBatchKMeans(n_clusters=int(cfg.get('vehicle_type_clusters', 6)), batch_size=64, random_state=17, n_init='auto')
        self.type_ready = False
        self.type_buf = []
        self.type_speed = defaultdict(lambda: deque(maxlen=1200))

        self.scaler = StandardScaler()
        self.clf = SGDClassifier(loss='log_loss', alpha=.0008, random_state=42)
        self.clf_ready = False
        self.supervised_n = 0
        self.safe_label_n = 0
        self.unsafe_label_n = 0
        self.geometry_label_n = 0
        self.min_balanced_class_samples = int(cfg.get('balanced_ml_min_per_class', 12))
        self.outcome_success_weight = float(cfg.get('outcome_success_weight', 3.0))
        self.outcome_failure_weight = float(cfg.get('outcome_failure_weight', 4.0))
        self.max_crash_samples_per_event = int(cfg.get('max_crash_samples_per_event', 2))

        # V4.2.7: crash fingerprints work before the supervised classifier has
        # balanced SAFE/UNSAFE labels.
        self.crash_memory_max = int(cfg.get('crash_memory_max', 240))
        self.safe_memory_max = int(cfg.get('safe_memory_max', 180))
        self.crash_memory_sigma = float(cfg.get('crash_memory_sigma', .72))
        self.crash_memory_half_life = float(
            cfg.get('crash_memory_half_life_seconds', 900.0)
        )
        self.crash_memory = deque(maxlen=self.crash_memory_max)
        self.safe_memory = deque(maxlen=self.safe_memory_max)

        self.observation_n = 0
        self.pattern_event_n = 0
        self.crash_count = 0
        self.crash_sample_n = 0
        stamp = time.strftime('%Y%m%d_%H%M%S')
        self.crash_log_path = self.folder / f"crashes_{stamp}.csv"
        self.state_log_path = self.folder / f"state_{stamp}.csv"
        self.event_log_path = self.folder / f"events_{stamp}.csv"
        self.state_rows = deque(maxlen=5000)
        self.event_rows = deque(maxlen=2000)
        self.last_state_log_ts = 0.0
        self.state_log_interval = float(cfg.get('state_log_interval_seconds', .10))
        self.min_event_track_age = int(cfg.get('min_event_track_age', 5))
        self.min_event_speed = float(cfg.get('min_event_speed_px_s', 20))
        self.min_event_vertical_speed = float(cfg.get('min_event_vertical_speed_px_s', 18))
        self.min_event_vertical_displacement = float(cfg.get('min_event_vertical_displacement_px', 30))
        self.min_event_vertical_ratio = float(
            cfg.get('min_event_vertical_ratio', 1.10)
        )
        self.min_event_direction_consistency = float(
            cfg.get('min_event_direction_consistency', .55)
        )
        self.expected_vehicle_vy_sign = 1
        self.reset_directional_learning_on_migration = bool(
            cfg.get('reset_directional_learning_on_migration', True)
        )
        self.min_valid_gap_seconds = float(cfg.get('min_valid_gap_seconds', 0.22))
        self.max_valid_gap_seconds = float(cfg.get('max_valid_gap_seconds', 5.0))
        self.pattern_segment_id = 0
        self.lane_stats = defaultdict(lambda: deque(maxlen=1800))

        # Event/pattern memory.
        self.events = defaultdict(lambda: deque(maxlen=500))
        self.pattern_gaps = defaultdict(lambda: deque(maxlen=300))
        # V3.0 global fallback lets a learned sequence survive local lane-ID
        # shifts between sessions/camera positions.
        self.global_pattern_gaps = defaultdict(lambda: deque(maxlen=600))

        # V3.5: sequence -> NEXT vehicle class learning.
        # This lets the model learn patterns such as:
        # F,F,M -> long gap -> usually SLOW vehicle.
        self.pattern_next = defaultdict(Counter)
        self.global_pattern_next = defaultdict(Counter)

        # V3.6 primary speed-only pattern learner. It accumulates much faster
        # than type-aware tokens and can discover S>F>F, F>F>F, etc.
        self.speed_pattern_gaps = defaultdict(lambda: deque(maxlen=500))
        self.global_speed_pattern_gaps = defaultdict(lambda: deque(maxlen=1000))
        self.speed_pattern_next = defaultdict(Counter)
        self.global_speed_pattern_next = defaultdict(Counter)

        self.candidate_speed_patterns = {
            tuple(x.split('>')) for x in cfg.get(
                'candidate_speed_patterns',
                ['S>F>F','F>F>F','S>S>F','F>S','S>F>M','S>F>F>S']
            )
        }
        self.candidate_min_support = int(cfg.get('candidate_min_support', 8))
        self.candidate_min_p25_gap = float(cfg.get('candidate_min_p25_gap_seconds', 1.0))
        self.candidate_max_fast_prob = float(cfg.get('candidate_max_next_fast_prob', .30))

        self.green_speed_successes = Counter()
        self.green_speed_failures = Counter()
        self.green_source_successes = Counter()
        self.green_source_failures = Counter()
        self.green_source_failure_etas = defaultdict(lambda: deque(maxlen=40))
        self.green_source_action_delays = defaultdict(lambda: deque(maxlen=40))
        self.green_source_late_action_delays = defaultdict(lambda: deque(maxlen=40))
        self.green_source_late_failures = Counter()
        self.green_late_action_observations = Counter()
        self.green_success_n = 0
        self.max_supervised_class_imbalance = float(
            cfg.get('max_supervised_class_imbalance', 4.0)
        )
        self.failure_eta_margin = float(
            cfg.get('failure_eta_margin_seconds', .24)
        )
        self.failure_eta_min_samples = int(
            cfg.get('failure_eta_min_samples', 2)
        )
        self.late_green_causal_max_seconds = float(
            cfg.get('late_green_causal_max_seconds', 2.2)
        )

        # Dedicated memory for CLEAR signals that were followed by a crash.
        stamp2 = time.strftime('%Y%m%d_%H%M%S')
        self.green_failure_log_path = self.folder / f"green_failures_{stamp2}.csv"
        self.green_outcome_log_path = self.folder / f"green_outcomes_{stamp2}.csv"
        self.green_failure_n = 0
        self.green_pattern_failures = Counter()

        self.last_side = {}
        self.seen_pass = set()
        self.max_pattern_order = int(cfg.get('max_pattern_order', 4))
        self.min_pattern_support = int(cfg.get('min_pattern_support', 3))
        self.event_dedup_seconds = float(cfg.get('event_dedup_seconds', .18))
        self.last_event_ts = {}

        self._checkpoint_thread=None
        self.last_model_save_ok=None
        self.last_model_save_ts=None
        self.last_model_save_error=''
        self.state_path = self.model_dir / 'online_state_v532.joblib'
        self.legacy_state_paths = [
            self.model_dir / 'online_state_v531.joblib',
            self.model_dir / 'online_state_v530.joblib',
            self.model_dir / 'online_state_v529.joblib',
            self.model_dir / 'online_state_v528.joblib',
            self.model_dir / 'online_state_v527.joblib',
            self.model_dir / 'online_state_v526.joblib',
            self.model_dir / 'online_state_v525.joblib',
            self.model_dir / 'online_state_v524.joblib',
            self.model_dir / 'online_state_v523.joblib',
            self.model_dir / 'online_state_v522.joblib',
            self.model_dir / 'online_state_v520.joblib',
            self.model_dir / 'online_state_v510.joblib',
            self.model_dir / 'online_state_v447.joblib',
            self.model_dir / 'online_state_v446.joblib',
            self.model_dir / 'online_state_v445.joblib',
            self.model_dir / 'online_state_v444.joblib',
            self.model_dir / 'online_state_v443.joblib',
            self.model_dir / 'online_state_v442.joblib',
            self.model_dir / 'online_state_v441.joblib',
            self.model_dir / 'online_state_v440.joblib',
            self.model_dir / 'online_state_v439.joblib',
            self.model_dir / 'online_state_v438.joblib',
            self.model_dir / 'online_state_v437.joblib',
            self.model_dir / 'online_state_v436.joblib',
            self.model_dir / 'online_state_v435.joblib',
            self.model_dir / 'online_state_v434.joblib',
            self.model_dir / 'online_state_v433.joblib',
            self.model_dir / 'online_state_v432.joblib',
            self.model_dir / 'online_state_v431.joblib',
            self.model_dir / 'online_state_v430.joblib',
            self.model_dir / 'online_state_v429.joblib',
            self.model_dir / 'online_state_v428.joblib',
            self.model_dir / 'online_state_v427.joblib',
            self.model_dir / 'online_state_v426.joblib',
            self.model_dir / 'online_state_v425.joblib',
            self.model_dir / 'online_state_v424.joblib',
            self.model_dir / 'online_state_v423.joblib',
            self.model_dir / 'online_state_v422.joblib',
            self.model_dir / 'online_state_v421.joblib',
            self.model_dir / 'online_state_v42.joblib',
            self.model_dir / 'online_state_v40.joblib',
            self.model_dir / 'online_state_v310.joblib',
            self.model_dir / 'online_state_v38.joblib',
            self.model_dir / 'online_state_v37.joblib',
        ]
        self._load()

    def _load(self):
        load_path = self.state_path
        migrating = False
        if not load_path.exists():
            for candidate in self.legacy_state_paths:
                if candidate.exists():
                    load_path = candidate
                    migrating = True
                    break
        if not load_path.exists():
            return
        source_state_name = load_path.name
        try:
            s = joblib.load(load_path)
            _green_policy_version=int(s.get('green_attribution_policy_version',0) or 0)
            compatible_migration = bool(migrating and source_state_name in ('online_state_v531.joblib','online_state_v530.joblib','online_state_v529.joblib','online_state_v528.joblib','online_state_v527.joblib','online_state_v526.joblib','online_state_v525.joblib','online_state_v524.joblib','online_state_v523.joblib','online_state_v522.joblib'))
            preserve_learned = bool((not migrating) or compatible_migration)
            self.cluster = s.get('cluster', self.cluster)
            self.cluster_ready = s.get('cluster_ready', False)
            self.type_cluster = s.get('type_cluster', self.type_cluster)
            self.type_ready = s.get('type_ready', False)

            # V3.6 deliberately resets the biased V3.5 danger classifier when
            # migrating, while preserving all pattern/speed/type knowledge.
            if preserve_learned:
                self.scaler = s.get('scaler', self.scaler)
                self.clf = s.get('clf', self.clf)
                self.clf_ready = s.get('clf_ready', False)
                self.supervised_n = int(s.get('supervised_n', 0))
                self.safe_label_n = int(s.get('safe_label_n', 0))
                self.unsafe_label_n = int(s.get('unsafe_label_n', 0))
                self.geometry_label_n = int(s.get('geometry_label_n', 0))
            else:
                self.scaler = StandardScaler()
                self.clf = SGDClassifier(loss='log_loss', alpha=.0008, random_state=42)
                self.clf_ready = False
                self.supervised_n = 0
                self.safe_label_n = 0
                self.unsafe_label_n = 0
                self.geometry_label_n = 0

            self.observation_n = int(s.get('observation_n', 0))
            self.pattern_event_n = int(s.get('pattern_event_n', 0))
            self.crash_count = int(s.get('crash_count', 0))
            self.crash_sample_n = int(s.get('crash_sample_n', 0))
            self.crash_memory.extend(s.get('crash_memory', []))
            # V5.1 migration intentionally does NOT import historical SAFE
            # memory. V5.0.x generated many false manual-success labels while
            # the single-lane ROI was stale. Crash/pattern/speed history remains
            # useful, but old positive outcome memory is contaminated.
            if preserve_learned:
                self.safe_memory.extend(s.get('safe_memory', []))
            self.event_speeds.extend(s.get('event_speeds', []))

            for k, vals in s.get('type_speed', {}).items():
                self.type_speed[int(k)].extend(vals)
            for k, vals in s.get('events', {}).items():
                self.events[int(k)].extend(vals)

            # V4.2.4: an application restart is a fresh live segment. Keep
            # historical pattern statistics as priors, but never continue the
            # active sequence from an older run/session.
            persisted_segments = [
                int(e.get('segment', -1))
                for hist in self.events.values()
                for e in hist
                if e.get('token') != '<RESET>'
            ]
            if persisted_segments:
                self.pattern_segment_id = max(persisted_segments) + 1
            self.last_event_ts = {}
            self.last_side = {}
            self.seen_pass = set()

            for k, vals in s.get('pattern_gaps', {}).items():
                self.pattern_gaps[k].extend(vals)
            for k, vals in s.get('global_pattern_gaps', {}).items():
                self.global_pattern_gaps[k].extend(vals)
            for k, vals in s.get('pattern_next', {}).items():
                self.pattern_next[k].update(vals)
            for k, vals in s.get('global_pattern_next', {}).items():
                self.global_pattern_next[k].update(vals)

            for k, vals in s.get('speed_pattern_gaps', {}).items():
                self.speed_pattern_gaps[k].extend(vals)
            for k, vals in s.get('global_speed_pattern_gaps', {}).items():
                self.global_speed_pattern_gaps[k].extend(vals)
            for k, vals in s.get('speed_pattern_next', {}).items():
                self.speed_pattern_next[k].update(vals)
            for k, vals in s.get('global_speed_pattern_next', {}).items():
                self.global_speed_pattern_next[k].update(vals)

            if preserve_learned:
                self.green_failure_n = int(s.get('green_failure_n', 0))
                self.green_success_n = int(s.get('green_success_n', 0))
                self.green_pattern_failures.update(s.get('green_pattern_failures', {}))
                self.green_source_failures.update(s.get('green_source_failures', {}))
                self.green_source_successes.update(s.get('green_source_successes', {}))
                for k, vals in s.get('green_source_failure_etas', {}).items():
                    self.green_source_failure_etas[str(k)].extend(vals)
                for k, vals in s.get('green_source_action_delays', {}).items():
                    self.green_source_action_delays[str(k)].extend(vals)
                for k, vals in s.get('green_source_late_action_delays', {}).items():
                    self.green_source_late_action_delays[str(k)].extend(vals)
                self.green_source_late_failures.update(
                    s.get('green_source_late_failures', {})
                )
                self.green_late_action_observations.update(
                    s.get('green_late_action_observations', {})
                )
                self.green_speed_successes.update(s.get('green_speed_successes', {}))
                self.green_speed_failures.update(s.get('green_speed_failures', {}))

                # V5.4.0 migration: V5.3.7 still had a separate 6-second
                # crash-progress fallback that could fabricate GREEN actions and
                # train fullscreen/multi-jump resets as GREEN failures. Preserve
                # successful timing/vehicle/pattern/crash memory, but drop all
                # GREEN-only failure counters/ETA floors once under policy 538.
                if _green_policy_version < 550:
                    # V5.5.0 migration: pre-550 GREEN failures may include
                    # stable landings that were later blamed after ROI rewarm
                    # hid the chicken from the outcome tracker. Drop only
                    # GREEN-specific negative memory; preserve successful
                    # timing, autonomous traffic learning and manual crash data.
                    self.green_failure_n = 0
                    self.green_pattern_failures.clear()
                    self.green_source_failures.clear()
                    self.green_source_failure_etas.clear()
                    self.green_source_late_failures.clear()
                    self.green_speed_failures.clear()
                    self.crash_memory = deque(
                        [p for p in self.crash_memory
                         if not str(p.get('source','')).startswith('acted_green_failure')],
                        maxlen=self.crash_memory_max
                    )
            else:
                # V3.6 outcome validation over-credited multi-jump states as
                # successes and missed reset crashes. Keep patterns, discard
                # those outcome labels and start V3.7 validation clean.
                self.green_failure_n = 0
                self.green_success_n = 0
                self.green_pattern_failures.clear()
                self.green_source_failures.clear()
                self.green_source_successes.clear()
                self.green_source_failure_etas.clear()
                self.green_source_action_delays.clear()
                self.green_source_late_failures.clear()
                self.green_late_action_observations.clear()
                self.green_speed_successes.clear()
                self.green_speed_failures.clear()

            if (
                migrating
                and source_state_name not in (
                    'online_state_v42.joblib',
                    'online_state_v421.joblib',
                    'online_state_v422.joblib',
                    'online_state_v423.joblib',
                    'online_state_v424.joblib',
                    'online_state_v425.joblib',
                    'online_state_v426.joblib',
                    'online_state_v427.joblib',
                    'online_state_v428.joblib',
                    'online_state_v429.joblib',
                    'online_state_v430.joblib',
                    'online_state_v447.joblib',
                    'online_state_v510.joblib',
                    'online_state_v520.joblib',
                    'online_state_v522.joblib',
                    'online_state_v523.joblib',
                    'online_state_v524.joblib',
                    'online_state_v525.joblib',
                    'online_state_v526.joblib',
                    'online_state_v527.joblib',
                    'online_state_v528.joblib',
                    'online_state_v529.joblib',
                    'online_state_v530.joblib',
                    'online_state_v531.joblib',
                )
                and self.reset_directional_learning_on_migration
            ):
                # Pre-V4.2 builds accepted both vy signs into traffic-event history.
                # The physical game traffic is confirmed TOP->BOTTOM (+Y), so
                # sequence timing/speed classes are relearned from clean +Y events.
                self.event_speeds.clear()
                self.type_speed.clear()
                self.events.clear()
                self.pattern_gaps.clear()
                self.global_pattern_gaps.clear()
                self.pattern_next.clear()
                self.global_pattern_next.clear()
                self.speed_pattern_gaps.clear()
                self.global_speed_pattern_gaps.clear()
                self.speed_pattern_next.clear()
                self.global_speed_pattern_next.clear()
                self.pattern_event_n = 0
                self.last_event_ts.clear()
                self.last_side.clear()
                self.seen_pass.clear()

                # Outcome classifier also restarts because its features were
                # produced from direction-contaminated traffic inputs.
                self.scaler = StandardScaler()
                self.clf = SGDClassifier(
                    loss='log_loss', alpha=.0008, random_state=42
                )
                self.clf_ready = False
                self.supervised_n = 0
                self.safe_label_n = 0
                self.unsafe_label_n = 0
                self.geometry_label_n = 0

                self.green_failure_n = 0
                self.green_success_n = 0
                self.green_pattern_failures.clear()
                self.green_source_failures.clear()
                self.green_source_successes.clear()
                self.green_source_failure_etas.clear()
                self.green_source_action_delays.clear()
                self.green_source_late_failures.clear()
                self.green_late_action_observations.clear()
                self.green_speed_successes.clear()
                self.green_speed_failures.clear()

            elif not self.global_speed_pattern_gaps:
                self._rebuild_speed_patterns_from_events()
        except Exception:
            pass


    def _rebuild_speed_patterns_from_events(self):
        """Reconstruct V3.6 speed-only pattern maps from migrated event history."""
        self.speed_pattern_gaps.clear()
        self.global_speed_pattern_gaps.clear()
        self.speed_pattern_next.clear()
        self.global_speed_pattern_next.clear()

        for lane, hist in self.events.items():
            segment_events = []
            for e in list(hist):
                if e.get('token') == '<RESET>':
                    segment_events = []
                    continue

                gap = e.get('gap')
                cls = e.get('class')
                if (
                    gap is not None and cls in ('S','M','F')
                    and self.min_valid_gap_seconds <= float(gap) <= self.max_valid_gap_seconds
                    and segment_events
                ):
                    speed_tokens = [x.get('class') for x in segment_events if x.get('class') in ('S','M','F')]
                    for n in range(1, min(self.max_pattern_order, len(speed_tokens)) + 1):
                        seq = tuple(speed_tokens[-n:])
                        self.speed_pattern_gaps[(int(lane), seq)].append(float(gap))
                        self.global_speed_pattern_gaps[seq].append(float(gap))
                        self.speed_pattern_next[(int(lane), seq)][cls] += 1
                        self.global_speed_pattern_next[seq][cls] += 1

                segment_events.append(e)

    def observe(self, tracks, lane_mapper=None):
        now = time.time()
        for t in tracks:
            speed = float(t['speed'])
            accel = float(t['accel'])
            lane = lane_mapper.lane_for(t['cx']) if lane_mapper else -1
            self.observation_n += 1
            self.speeds.append(speed)
            self.rows.append([
                now, t['id'], lane, t['cx'], t['cy'], t['vx'], t['vy'],
                speed, accel, t['w'], t['h'], t.get('mean_h', 0), t.get('mean_s', 0), t.get('mean_v', 0)
            ])
            self.speed_buf.append([speed, abs(accel), t['w']/100.0, t['h']/100.0])
            self.type_buf.append(self._type_features(t))
            if lane >= 0 and speed > 8:
                self.lane_stats[lane].append((speed, float(t['vy'])))

        if len(self.speed_buf) >= 24:
            x = np.asarray(self.speed_buf, dtype=np.float32)
            try:
                self.cluster.partial_fit(x)
                self.cluster_ready = True
            except ValueError:
                pass
            self.speed_buf.clear()

        # Need at least n_clusters samples before first partial_fit.
        min_type = max(24, self.type_cluster.n_clusters * 4)
        if len(self.type_buf) >= min_type:
            x = np.asarray(self.type_buf, dtype=np.float32)
            try:
                self.type_cluster.partial_fit(x)
                self.type_ready = True
            except ValueError:
                pass
            self.type_buf.clear()

        if self.type_ready:
            for t in tracks:
                typ = self.vehicle_type(t)
                if typ >= 0 and float(t['speed']) > 8:
                    self.type_speed[typ].append(float(t['speed']))

    @staticmethod
    def _type_features(t):
        return [
            float(t.get('w', 0))/120.0,
            float(t.get('h', 0))/160.0,
            float(t.get('mean_h', 0))/179.0,
            float(t.get('mean_s', 0))/255.0,
            float(t.get('mean_v', 0))/255.0,
        ]

    def vehicle_type(self, track):
        if not self.type_ready:
            return -1
        x = np.asarray([self._type_features(track)], dtype=self.type_cluster.cluster_centers_.dtype)
        try:
            return int(self.type_cluster.predict(x)[0])
        except Exception:
            return -1

    def type_expected_speed(self, typ):
        a = list(self.type_speed.get(int(typ), []))
        if len(a) < 8:
            return None
        return float(np.median(np.asarray(a)))

    def speed_thresholds(self):
        """Adaptive S/M/F boundaries from confirmed crossing events only."""
        if len(self.event_speeds) < self.speed_min_events:
            return self.speed_fallback_slow, self.speed_fallback_fast

        a = np.asarray(self.event_speeds, dtype=float)
        # Trim extreme tracker glitches before computing percentiles.
        lo_clip = float(np.percentile(a, 5))
        hi_clip = float(np.percentile(a, 95))
        a = a[(a >= lo_clip) & (a <= hi_clip)]
        if len(a) < max(8, self.speed_min_events // 2):
            return self.speed_fallback_slow, self.speed_fallback_fast

        lo = float(np.percentile(a, self.speed_slow_percentile))
        hi = float(np.percentile(a, self.speed_fast_percentile))

        # Prevent the medium band from collapsing when speeds cluster tightly.
        if hi - lo < self.speed_min_band_px_s:
            mid = float(np.median(a))
            half = self.speed_min_band_px_s / 2.0
            lo = max(5.0, mid - half)
            hi = mid + half

        return lo, hi

    def speed_class(self, speed):
        speed = float(speed)
        lo, hi = self.speed_thresholds()
        return 'S' if speed < lo else 'M' if speed < hi else 'F'

    def is_fast(self, speed):
        return self.speed_class(speed) == 'F'

    def lane_summary(self, lane):
        a = list(self.lane_stats.get(lane, []))
        if not a:
            return {'mean_speed': 0.0, 'p90_speed': 0.0, 'direction': 0.0}
        s = np.asarray([x[0] for x in a])
        vy = np.asarray([x[1] for x in a])
        return {
            'mean_speed': float(s.mean()),
            'p90_speed': float(np.percentile(s, 90)),
            'direction': float(np.sign(np.median(vy))),
        }

    def reset_pattern_timing(self, reason='reset'):
        """Start a new traffic segment without deleting learned statistics.

        This prevents the next vehicle after a crash/reset/pause from creating
        a huge fake inter-vehicle gap.
        """
        self.pattern_segment_id += 1
        self.last_event_ts = {}
        self.last_side = {}
        # Keep historical pattern_gaps/events for learning, but mark a segment
        # boundary so sequence construction won't cross resets.
        for lane in list(self.events.keys()):
            self.events[lane].append({
                'ts': time.time(), 'class': '|', 'type': -1,
                'token': '<RESET>', 'gap': None, 'segment': self.pattern_segment_id
            })

    def observe_pass_events(self, tracks, lane_mapper, chicken, watched_lane=None):
        """Record ONE confirmed vehicle-crossing event per physical pass.

        Raw tracker IDs are intentionally not trusted immediately. A track must
        survive several matched frames, move mostly vertically, accumulate real
        vertical displacement, and cross the chicken's Y line before it can
        enter the traffic-pattern learner.
        """
        if chicken is None or not lane_mapper.ready:
            return

        cy = float(chicken['cy'])
        now = time.time()

        for t in tracks:
            tid = int(t['id'])
            if watched_lane is not None:
                try:
                    lane = int(watched_lane)
                except Exception:
                    lane = lane_mapper.lane_for(t['cx'])
            else:
                lane = lane_mapper.lane_for(t['cx'])
            if lane < 0:
                continue

            age = int(t.get('age', 0))
            matched = int(t.get('matched_count', age))
            speed = float(t.get('speed', 0.0))
            vx = float(t.get('vx', 0.0))
            vy = float(t.get('vy', 0.0))
            forward_vy = max(
                0.0,
                vy,
                float(t.get('fit_vy', vy)),
                float(t.get('net_vy', vy)),
            )
            direction_valid = bool(
                t.get(
                    'direction_valid',
                    forward_vy >= self.min_event_vertical_speed
                )
            )
            direction_consistency = float(
                t.get('direction_consistency', 1.0)
            )
            displacement_y = abs(
                float(t.get('cy', 0.0))
                - float(
                    t.get('start_cy', t.get('cy', 0.0))
                )
            )

            confirmed = (
                age >= self.min_event_track_age and
                matched >= self.min_event_track_age and
                speed >= self.min_event_speed and
                forward_vy >= self.min_event_vertical_speed and
                direction_valid and
                direction_consistency
                    >= self.min_event_direction_consistency and
                displacement_y >= self.min_event_vertical_displacement
            )
            if not confirmed:
                continue

            side = float(t['cy']) - cy
            prev = self.last_side.get(tid)
            self.last_side[tid] = side

            crossed = prev is not None and (prev < 0 <= side)
            # First observation close to crossing can still be accepted, but
            # only after the track itself is already confirmed.
            near = abs(side) <= max(
                10.0,
                min(36.0, float(forward_vy) * 0.060)
            )

            if tid in self.seen_pass or not (crossed or (prev is None and near)):
                continue

            self.seen_pass.add(tid)
            self._record_event(lane, now, t)

        if len(self.seen_pass) > 12000:
            active = {int(t['id']) for t in tracks}
            self.seen_pass = {tid for tid in self.seen_pass if tid in active}

    def _record_event(self, lane, ts, track):
        lane = int(lane)
        ts = float(ts)

        prev_ts = self.last_event_ts.get(lane)
        if prev_ts is not None and ts - float(prev_ts) < self.event_dedup_seconds:
            return

        history = self.events[lane]
        confirmed_speed = float(track['speed'])
        forward_speed = max(
            0.0,
            float(track.get('vy', 0.0)),
            float(track.get('fit_vy', track.get('vy', 0.0))),
            float(track.get('net_vy', track.get('vy', 0.0))),
        )
        cls = self.speed_class(confirmed_speed)
        forward_cls = self.speed_class(forward_speed)
        typ = self.vehicle_type(track)

        raw_gap = None if prev_ts is None else max(0.0, ts - float(prev_ts))
        self.last_event_ts[lane] = ts

        # Only realistic consecutive-vehicle gaps are trainable. A very long
        # pause or an implausibly short gap is a segment boundary, not traffic.
        gap = raw_gap
        if gap is not None and not (
            self.min_valid_gap_seconds <= gap <= self.max_valid_gap_seconds
        ):
            gap = None

        # The newly observed gap is the OUTCOME following the preceding sequence.
        # Do not let patterns cross a reset/segment boundary.
        if gap is not None:
            prev_events = [
                e for e in history
                if e.get('token') != '<RESET>'
                and e.get('segment', self.pattern_segment_id) == self.pattern_segment_id
            ]
            tokens = [e['token'] for e in prev_events]
            for n in range(1, min(self.max_pattern_order, len(tokens)) + 1):
                seq = tuple(tokens[-n:])
                if not seq:
                    continue
                self.pattern_gaps[(lane, seq)].append(float(gap))
                self.global_pattern_gaps[seq].append(float(gap))

                # The CURRENT vehicle is the observed outcome following seq.
                self.pattern_next[(lane, seq)][cls] += 1
                self.global_pattern_next[seq][cls] += 1

            speed_tokens = [e['class'] for e in prev_events]
            for n in range(1, min(self.max_pattern_order, len(speed_tokens)) + 1):
                sseq = tuple(speed_tokens[-n:])
                if not sseq:
                    continue
                self.speed_pattern_gaps[(lane, sseq)].append(float(gap))
                self.global_speed_pattern_gaps[sseq].append(float(gap))
                self.speed_pattern_next[(lane, sseq)][cls] += 1
                self.global_speed_pattern_next[sseq][cls] += 1

        token = f'{cls}T{typ}' if typ >= 0 else cls
        history.append({
            'ts': ts,
            'class': cls,
            'type': int(typ),
            'token': token,
            'gap': gap,
            'speed': confirmed_speed,
            'forward_speed': float(forward_speed),
            'forward_class': str(forward_cls),
            'segment': self.pattern_segment_id,
        })

        self.event_speeds.append(confirmed_speed)
        self.pattern_event_n += 1
        self.event_rows.append([
            ts, lane, int(track.get('id', -1)), token, cls, int(typ),
            confirmed_speed, float(track.get('vx', 0.0)),
            float(track.get('vy', 0.0)),
            '' if gap is None else float(gap),
            int(track.get('age', 0)),
            abs(float(track.get('cy', 0.0)) -
                float(track.get('start_cy', track.get('cy', 0.0))))
        ])


    def recent_lane_events(self, lane, now=None, seconds=90.0, current_segment_only=True):
        """Return recent confirmed crossing events for live regime calibration."""
        now = float(now or time.time())
        hist = [e for e in list(self.events.get(int(lane), [])) if e.get('token') != '<RESET>']
        if current_segment_only and hist:
            seg = hist[-1].get('segment', self.pattern_segment_id)
            hist = [e for e in hist if e.get('segment', seg) == seg]
        lo = now - float(seconds)
        return [dict(e) for e in hist if float(e.get('ts', 0.0)) >= lo]

    def recent_events_all_lanes(self, now=None, seconds=180.0):
        """Recent confirmed vehicle crossings across reset segments.

        Crash/reset boundaries still split pattern sequences, but speed / traffic
        calibration must not be erased every time the chicken dies.  This is
        deliberately rolling and never builds sequences across resets.
        """
        now = float(now or time.time())
        lo = now - float(seconds)
        out = []
        for lane, hist in self.events.items():
            for e in list(hist):
                if e.get('token') == '<RESET>':
                    continue
                if float(e.get('ts', 0.0)) < lo:
                    continue
                out.append(dict(e))
        out.sort(key=lambda e: float(e.get('ts', 0.0)))
        return out

    def current_session_events_all_lanes(self):
        """Confirmed crossing events created since this app process started.

        Unlike the rolling 180 s calibration view, this preserves evidence that
        the current game has already contained fast vehicles even after a long
        quiet stretch. Persisted events from older runs are excluded.
        """
        out=[]
        lo=float(self.session_started_ts)-1.0
        for lane,hist in self.events.items():
            for e in list(hist):
                if e.get('token') == '<RESET>':
                    continue
                if float(e.get('ts',0.0)) < lo:
                    continue
                out.append(dict(e))
        out.sort(key=lambda e: float(e.get('ts',0.0)))
        return out

    def recent_segment_events_all_lanes(self, now=None, seconds=90.0):
        """Recent confirmed +Y events from the current post-reset segment."""
        now = float(now or time.time())
        lo = now - float(seconds)
        out = []
        for lane, hist in self.events.items():
            for e in list(hist):
                if e.get('token') == '<RESET>':
                    continue
                if int(e.get('segment', -1)) != int(self.pattern_segment_id):
                    continue
                if float(e.get('ts', 0.0)) < lo:
                    continue
                out.append(dict(e))
        out.sort(key=lambda e: float(e.get('ts', 0.0)))
        return out

    def current_segment_events_all_lanes(self):
        """ALL confirmed +Y events since the last crash/reset.

        Unlike the V4.2.2 rolling 90 s view, this count never decreases while
        the current run remains active. It is the correct quantity for deciding
        whether current-session CZN calibration has matured.
        """
        out = []
        for lane, hist in self.events.items():
            for e in list(hist):
                if e.get('token') == '<RESET>':
                    continue
                if int(e.get('segment', -1)) != int(self.pattern_segment_id):
                    continue
                out.append(dict(e))
        out.sort(key=lambda e: float(e.get('ts', 0.0)))
        return out

    def current_segment_lane_events(self, lane):
        """Confirmed events for one lane in the active crash/reset segment."""
        lane = int(lane)
        return [
            dict(e) for e in list(self.events.get(lane, []))
            if e.get('token') != '<RESET>'
            and int(e.get('segment', -1)) == int(self.pattern_segment_id)
        ]

    def latest_lane_event(self, lane, now=None, seconds=3.0):
        lane = int(lane)
        now = float(now or time.time())
        lo = now - float(seconds)
        evs = [
            dict(e) for e in list(self.events.get(lane, []))
            if e.get('token') != '<RESET>'
            and int(e.get('segment', -1)) == int(self.pattern_segment_id)
            and float(e.get('ts', 0.0)) >= lo
        ]
        if not evs:
            return None
        evs.sort(key=lambda e: float(e.get('ts', 0.0)))
        return evs[-1]

    def slow_anchor_profile(self,lane,min_lane_support=6,now=None,directional=True):
        return build_slow_profile(self.events,lane,self.pattern_segment_id,
            self.min_valid_gap_seconds,self.max_valid_gap_seconds,
            int(min_lane_support),time.time() if now is None else float(now),
            directional=bool(directional))

    def current_segment_speed_pattern_stats(self, lane, sequence):
        """Observed outcomes of a speed sequence inside the CURRENT segment."""
        if not sequence or sequence == '-':
            return {
                'support': 0, 'p25_gap': None, 'p_next_fast': 1.0,
                'gaps': []
            }
        seq = tuple(str(sequence).split('>'))
        hist = self.current_segment_lane_events(lane)
        if len(hist) <= len(seq):
            return {
                'support': 0, 'p25_gap': None, 'p_next_fast': 1.0,
                'gaps': []
            }

        classes = [str(e.get('class', 'M')) for e in hist]
        gaps = []
        next_classes = []
        n = len(seq)
        for i in range(n, len(hist)):
            if tuple(classes[i-n:i]) != seq:
                continue
            g = hist[i].get('gap')
            if g is None:
                continue
            g = float(g)
            if not (self.min_valid_gap_seconds <= g <= self.max_valid_gap_seconds):
                continue
            gaps.append(g)
            next_classes.append(str(hist[i].get('class','M')))

        if not gaps:
            return {
                'support': 0, 'p25_gap': None, 'p_next_fast': 1.0,
                'gaps': []
            }

        return {
            'support': len(gaps),
            'p25_gap': float(np.percentile(np.asarray(gaps,dtype=float),25)),
            'p_next_fast': float(
                sum(c == 'F' for c in next_classes) / len(next_classes)
            ),
            'gaps': gaps,
        }


    def pattern_prediction(self, lane, now=None):
        now = float(now or time.time())
        history = [
            e for e in list(self.events.get(int(lane), []))
            if e.get('token') != '<RESET>'
            and int(e.get('segment', -1)) == int(self.pattern_segment_id)
        ]
        if not history:
            return {
                'ready': False, 'support': 0, 'sequence': '-', 'expected_gap': None,
                'remaining': None, 'break_score': 0.0, 'confidence': 0.0, 'source': 'none'
            }
        tokens = [e['token'] for e in history]
        chosen = None

        # Prefer the longest lane-specific sequence with enough support.
        for n in range(min(self.max_pattern_order, len(tokens)), 0, -1):
            seq = tuple(tokens[-n:])
            vals = list(self.pattern_gaps.get((int(lane), seq), []))
            if len(vals) >= self.min_pattern_support:
                chosen = (seq, vals, 'lane')
                break

        # If the local lane ID has shifted or is young, use a global sequence
        # learned from confirmed crossings on all lanes.
        if chosen is None:
            for n in range(min(self.max_pattern_order, len(tokens)), 0, -1):
                seq = tuple(tokens[-n:])
                vals = list(self.global_pattern_gaps.get(seq, []))
                if len(vals) >= max(self.min_pattern_support + 1, 5):
                    chosen = (seq, vals, 'global')
                    break

        if chosen is None:
            vals = [
                float(e['gap']) for e in history
                if e.get('gap') is not None and
                self.min_valid_gap_seconds <= float(e['gap']) <= self.max_valid_gap_seconds
            ]
            if len(vals) < self.min_pattern_support:
                return {
                    'ready': False, 'support': len(vals),
                    'sequence': tokens[-1] if tokens else '-',
                    'expected_gap': None, 'remaining': None,
                    'break_score': 0.0, 'confidence': 0.0, 'source': 'none'
                }
            seq = tuple(tokens[-1:])
            source = 'lane_baseline'
        else:
            seq, vals, source = chosen

        arr = np.asarray(vals, dtype=float)
        expected = float(np.median(arr))
        p25 = float(np.percentile(arr, 25))
        p75 = float(np.percentile(arr, 75))
        elapsed = max(0.0, now - float(history[-1]['ts']))
        remaining = expected - elapsed

        if elapsed > self.max_valid_gap_seconds + .35:
            return {
                'ready': False, 'expired': True, 'support': len(vals),
                'sequence': '>'.join(seq), 'expected_gap': expected,
                'remaining': None, 'elapsed': elapsed,
                'p25_gap': p25, 'p75_gap': p75,
                'break_score': 0.0, 'confidence': 0.0, 'source': source,
                'p_next_slow': 0.0, 'p_next_medium': 0.0,
                'p_next_fast': 0.0, 'slow_after_gap_score': 0.0,
            }

        allg = np.asarray([
            e['gap'] for e in history
            if e.get('gap') is not None and
            self.min_valid_gap_seconds <= float(e['gap']) <= self.max_valid_gap_seconds
        ], dtype=float)
        baseline = float(np.median(allg)) if len(allg) else expected
        break_score = float(np.clip((p75 - baseline) / max(0.18, baseline), 0.0, 2.0) / 2.0)

        # Confidence grows with repetitions and longer sequence order, but does
        # not pretend that a handful of repeats is certainty.
        support = len(vals)
        order_bonus = min(1.0, len(seq) / max(2.0, float(self.max_pattern_order)))
        support_score = 1.0 - math.exp(-support / 8.0)
        confidence = float(np.clip(0.75 * support_score + 0.25 * order_bonus, 0.0, 1.0))
        if source == 'global':
            confidence *= 0.85
        elif source == 'lane_baseline':
            confidence *= 0.55

        # Learn what class usually follows this sequence.
        if source == 'lane':
            nxt = Counter(self.pattern_next.get((int(lane), seq), {}))
        else:
            nxt = Counter(self.global_pattern_next.get(seq, {}))

        next_total = sum(nxt.values())
        p_next_slow = (nxt.get('S', 0) / next_total) if next_total else 0.0
        p_next_medium = (nxt.get('M', 0) / next_total) if next_total else 0.0
        p_next_fast = (nxt.get('F', 0) / next_total) if next_total else 0.0

        # A useful "gap then slow car" score. It is only context; visible
        # geometry still has final authority in the risk engine.
        gap_factor = float(np.clip((expected - 0.8) / 1.8, 0.0, 1.0))
        slow_after_gap_score = float(
            np.clip(confidence * gap_factor * p_next_slow, 0.0, 1.0)
        )

        return {
            'ready': True,
            'support': support,
            'sequence': '>'.join(seq),
            'expected_gap': expected,
            'remaining': remaining,
            'elapsed': elapsed,
            'p25_gap': p25,
            'p75_gap': p75,
            'break_score': break_score,
            'confidence': confidence,
            'source': source,
            'next_support': next_total,
            'p_next_slow': p_next_slow,
            'p_next_medium': p_next_medium,
            'p_next_fast': p_next_fast,
            'slow_after_gap_score': slow_after_gap_score,
        }

    def speed_pattern_prediction(self, lane, now=None):
        """Primary sequence learner using only S/M/F classes."""
        now = float(now or time.time())
        history = [
            e for e in list(self.events.get(int(lane), []))
            if e.get('token') != '<RESET>'
            and int(e.get('segment', -1)) == int(self.pattern_segment_id)
        ]
        if not history:
            return {
                'ready': False, 'support': 0, 'sequence': '-',
                'expected_gap': None, 'remaining': None, 'confidence': 0.0,
                'source': 'none', 'p_next_slow': 0.0,
                'p_next_medium': 0.0, 'p_next_fast': 0.0,
                'candidate': False, 'candidate_validated': False,
            }

        tokens = [e['class'] for e in history]
        chosen = None

        for n in range(min(self.max_pattern_order, len(tokens)), 0, -1):
            seq = tuple(tokens[-n:])
            vals = list(self.speed_pattern_gaps.get((int(lane), seq), []))
            if len(vals) >= self.min_pattern_support:
                chosen = (seq, vals, 'lane')
                break

        if chosen is None:
            for n in range(min(self.max_pattern_order, len(tokens)), 0, -1):
                seq = tuple(tokens[-n:])
                vals = list(self.global_speed_pattern_gaps.get(seq, []))
                if len(vals) >= max(self.min_pattern_support + 1, 5):
                    chosen = (seq, vals, 'global')
                    break

        if chosen is None:
            return {
                'ready': False, 'support': 0,
                'sequence': '>'.join(tokens[-min(3, len(tokens)):]),
                'expected_gap': None, 'remaining': None, 'confidence': 0.0,
                'source': 'none', 'p_next_slow': 0.0,
                'p_next_medium': 0.0, 'p_next_fast': 0.0,
                'candidate': tuple(tokens[-3:]) in self.candidate_speed_patterns if len(tokens) >= 3 else False,
                'candidate_validated': False,
            }

        seq, vals, source = chosen
        arr = np.asarray(vals, dtype=float)
        expected = float(np.median(arr))
        p25 = float(np.percentile(arr, 25))
        p75 = float(np.percentile(arr, 75))
        elapsed = max(0.0, now - float(history[-1]['ts']))
        remaining = expected - elapsed

        # An expected next vehicle that is already many seconds overdue is not
        # a live pattern prediction. V4.2.3 logged remaining values around
        # -10 to -44 seconds while still calling the pattern ready.
        if elapsed > self.max_valid_gap_seconds + .35:
            return {
                'ready': False,
                'expired': True,
                'support': len(vals),
                'sequence': '>'.join(seq),
                'expected_gap': expected,
                'remaining': None,
                'elapsed': elapsed,
                'p25_gap': p25,
                'p75_gap': p75,
                'confidence': 0.0,
                'source': source,
                'p_next_slow': 0.0,
                'p_next_medium': 0.0,
                'p_next_fast': 0.0,
                'candidate': seq in self.candidate_speed_patterns,
                'candidate_validated': False,
            }

        support = len(vals)
        order_bonus = min(1.0, len(seq) / max(2.0, float(self.max_pattern_order)))
        support_score = 1.0 - math.exp(-support / 7.0)
        confidence = float(np.clip(0.78 * support_score + 0.22 * order_bonus, 0.0, 1.0))
        if source == 'global':
            confidence *= .88

        nxt = Counter(
            self.speed_pattern_next.get((int(lane), seq), {})
            if source == 'lane'
            else self.global_speed_pattern_next.get(seq, {})
        )
        total = sum(nxt.values())
        p_s = nxt.get('S', 0) / total if total else 0.0
        p_m = nxt.get('M', 0) / total if total else 0.0
        p_f = nxt.get('F', 0) / total if total else 0.0

        gap_factor = float(np.clip((expected - .8) / 1.8, 0.0, 1.0))
        slow_after_gap = float(np.clip(confidence * gap_factor * p_s, 0.0, 1.0))

        key = '>'.join(seq)
        successes = int(self.green_speed_successes.get(key, 0))
        failures = int(self.green_speed_failures.get(key, 0))
        acted = successes + failures
        success_rate = successes / acted if acted else None

        candidate = seq in self.candidate_speed_patterns
        validated = bool(
            support >= self.candidate_min_support
            and p25 >= self.candidate_min_p25_gap
            and p_f <= self.candidate_max_fast_prob
            and (acted < 3 or success_rate >= .75)
        )

        return {
            'ready': True,
            'support': support,
            'sequence': key,
            'expected_gap': expected,
            'remaining': remaining,
            'elapsed': elapsed,
            'p25_gap': p25,
            'p75_gap': p75,
            'confidence': confidence,
            'source': source,
            'next_support': total,
            'p_next_slow': p_s,
            'p_next_medium': p_m,
            'p_next_fast': p_f,
            'slow_after_gap_score': slow_after_gap,
            'candidate': candidate,
            'candidate_validated': validated,
            'green_successes': successes,
            'green_failures': failures,
            'green_success_rate': success_rate,
        }

    def log_state(self, state, chicken, tracks, crash_event=None):
        """Log decision-layer state at a controlled rate for later validation."""
        now = time.time()
        crash_flag = 1 if crash_event else 0
        if not crash_flag and now - self.last_state_log_ts < self.state_log_interval:
            return
        self.last_state_log_ts = now

        l1 = state.get('lane1') or {}
        l2 = state.get('lane2') or {}
        self.state_rows.append([
            now,
            '' if chicken is None else float(chicken.get('cx', 0.0)),
            '' if chicken is None else float(chicken.get('cy', 0.0)),
            state.get('lane', ''),
            state.get('lane2_id', ''),
            float(state.get('raw_risk', state.get('risk', 50.0))),
            float(state.get('display_risk', state.get('risk', 50.0))),
            float(state.get('risk_mean', 0.0)),
            float(state.get('risk_std', 0.0)),
            float(state.get('risk_max', 0.0)),
            state.get('indicator_state', ''),
            int(bool(state.get('green_confirmed', False))),
            int(bool(state.get('visible_threat', False))),
            state.get('threat_id', ''),
            '' if state.get('tti') is None else float(state.get('tti')),
            float(state.get('safe_window', 0.0)),
            float(l1.get('direct_risk', 0.0)) if l1 else '',
            float(l1.get('pattern_risk', 0.0)) if l1 else '',
            float(l1.get('ml_risk', 0.0)) if l1 else '',
            float(l2.get('risk', 0.0)) if l2 else '',
            state.get('pattern_text', ''),
            len(tracks),
            crash_flag,
            '' if not crash_event else crash_event.get('reason', ''),
            self.crash_count,
            self.crash_sample_n,
            self.pattern_event_n,
            self.supervised_n,
            int(bool(state.get('eta_gate_ok', False))),
            '' if state.get('clear_eta') is None else float(state.get('clear_eta')),
            state.get('clear_block_reason', ''),
            state.get('eta_source_for_gate', state.get('eta_source','unknown')),
            '' if state.get('required_clear_eta') is None else float(state.get('required_clear_eta')),
            int((l1.get('pattern') or {}).get('support', 0)) if l1 else 0,
            float((l1.get('pattern') or {}).get('confidence', 0.0)) if l1 else 0.0,
            (l1.get('pattern') or {}).get('source', '') if l1 else '',
            '' if not l1 or (l1.get('pattern') or {}).get('expected_gap') is None else float((l1.get('pattern') or {}).get('expected_gap')),
            '' if not l1 or (l1.get('pattern') or {}).get('remaining') is None else float((l1.get('pattern') or {}).get('remaining')),
            state.get('eta_source', 'unknown'),
            '' if state.get('direct_eta') is None else float(state.get('direct_eta')),
            '' if state.get('pattern_eta') is None else float(state.get('pattern_eta')),
            '' if state.get('clear_zone_eta') is None else float(state.get('clear_zone_eta')),
            float(state.get('clear_zone_direction', 0.0)),
            '' if state.get('clear_zone_distance') is None else float(state.get('clear_zone_distance')),
            '' if state.get('effective_eta') is None else float(state.get('effective_eta')),
            int(bool(chicken is not None and chicken.get('detected', True))),
            int(bool(chicken is not None and chicken.get('pending_position', False))),
            float(l1.get('p_next_slow', 0.0)) if l1 else 0.0,
            float(l1.get('p_next_medium', 0.0)) if l1 else 0.0,
            float(l1.get('p_next_fast', 0.0)) if l1 else 0.0,
            float(l1.get('slow_after_gap_score', 0.0)) if l1 else 0.0,
            float(l1.get('green_failure_penalty', 0.0)) if l1 else 0.0,
            int(self.green_failure_n),
            int(self.green_success_n),
            int(self.safe_label_n),
            int(self.unsafe_label_n),
            float(l1.get('ml_adjustment', 0.0)) if l1 else 0.0,
            str((l1.get('pattern') or {}).get('sequence','')) if l1 else '',
            int((l1.get('pattern') or {}).get('candidate', False)) if l1 else 0,
            int((l1.get('pattern') or {}).get('candidate_validated', False)) if l1 else 0,
            '' if not l1 or (l1.get('pattern') or {}).get('green_success_rate') is None else float((l1.get('pattern') or {}).get('green_success_rate')),
            int(bool(state.get('lane_visibility_ok', False))),
            float(state.get('lane_visibility_score', 0.0)),
            float(state.get('lane_mean_gray', 0.0)),
            float(state.get('lane_dark_ratio', 1.0)),
            float(state.get('clear_dwell', 0.0)),
            float(state.get('recent_threat_age', 0.0)),
            '' if state.get('pattern_p25_remaining') is None else float(state.get('pattern_p25_remaining')),
            int(bool(state.get('pattern_guard_ok', False))),
            int(bool(state.get('green_evidence_ok', False))),
            state.get('green_evidence_reason', ''),
            float(state.get('eta_source_reliability', 0.0)),
            int(state.get('eta_source_attempts', 0)),
            '' if state.get('green_required_eta') is None else float(state.get('green_required_eta')),
            int(state.get('regime_id', 0)),
            int(state.get('regime_samples', 0)),
            state.get('regime_reason', ''),
            float(state.get('adaptive_confidence', 0.0)),
            float(state.get('adaptive_required_confidence', 0.0)),
            float(state.get('adaptive_required_dwell', 0.0)),
            float(state.get('regime_speed_p90', 0.0)),
            float(state.get('regime_gap_p25', 0.0)),
            float(state.get('regime_gap_cv', 0.0)),
            float(state.get('regime_fast_fraction', 0.0)),
            int(state.get('recent_regime_crashes', 0)),
            int(state.get('recent_green_successes', 0)),
            int(state.get('recent_green_failures', 0)),
            float(state.get('recent_green_reliability', 0.0)),
            int(state.get('green_late_unattributed', 0)),
            float(state.get('post_green_action_grace', 0.18)),
            int(bool(state.get('czn_calibrated', False))),
            int(state.get('czn_confirmed_events', 0)),
            int(state.get('czn_required_events', 0)),
            int(state.get('czn_raw_speed_samples', 0)),
            int(state.get('czn_unique_raw_tracks', 0)),
            int(state.get('czn_required_unique_tracks', 0)),
            state.get('czn_calibration_mode', 'WAIT'),
            float(state.get('czn_calibration_age', 0.0)),
            float(state.get('czn_event_speed_p95', 0.0)),
            float(state.get('czn_raw_speed_p95', 0.0)),
            float(state.get('czn_speed_reference', 0.0)),
            int(state.get('uncertain_incoming_count', 0)),
            int(state.get('current_pattern_support', 0)),
            '' if state.get('current_pattern_p25') is None else float(state.get('current_pattern_p25')),
            float(state.get('current_pattern_p_next_fast', 1.0)),
            float(state.get('evidence_stable_elapsed', 0.0)),
            float(state.get('evidence_stable_required', 0.0)),
            int(bool(state.get('evidence_ready', False))),
            int(bool(state.get('motion_corridor_available', False))),
            int(bool(state.get('motion_corridor_clear', False))),
            float(state.get('motion_corridor_ratio', 1.0)),
            float(state.get('motion_clear_dwell', 0.0)),
            float(state.get('stage_difficulty_score', 0.0)),
            int(state.get('stage_profile_support', 0)),
            float(state.get('stage_speed_p95', 0.0)),
            float(state.get('stage_gap_p25', 0.0)),
            float(state.get('stage_speed_reference', 0.0)),
            float(state.get('crash_memory_score', 0.0)),
            int(state.get('crash_memory_matches', 0)),
            float(state.get('crash_memory_safe_similarity', 0.0)),
            float(state.get('processing_fps',0.0)),
            float(state.get('processing_lag_ms',0.0)),
            int(bool(state.get('processing_healthy',False))),
            int(bool(state.get('processing_degraded',False))),
            float(state.get('processing_green_floor_fps',0.0)),
            state.get('tracking_roi_lane',''),
            float(state.get('tracking_roi_area_pct',100.0)),
            int(bool(state.get('tracking_roi_fallback_hold',False))),
            int(state.get('tracking_roi_fallback_holds',0)),
            int(bool(state.get('two_lane_learning',False))),
            state.get('lookahead_lane',''),
            float(state.get('lookahead_risk',0.0)),
            int(state.get('lookahead_candidate_count',0)),
            int(bool(state.get('lookahead_visible_threat',False))),
            float(state.get('lookahead_clear_dwell',0.0)),
            float(state.get('lookahead_motion_clear_dwell',0.0)),
            float(state.get('lookahead_motion_ratio',1.0)),
            float(state.get('lookahead_stage_difficulty',0.0)),
            float(state.get('lookahead_stage_speed_p95',0.0)),
            state.get('slow_window_mode',''),
            int(state.get('slow_window_profile_support',0)),
            int(state.get('slow_window_lane_support',0)),
            float(state.get('slow_window_profile_confidence',0.0)),
            float(state.get('slow_window_p_fast',1.0)),
            '' if state.get('slow_window_p25_gap') is None else float(state.get('slow_window_p25_gap')),
            '' if state.get('slow_window_median_gap') is None else float(state.get('slow_window_median_gap')),
            '' if state.get('slow_window_eta') is None else float(state.get('slow_window_eta')),
            '' if state.get('slow_window_required_eta') is None else float(state.get('slow_window_required_eta')),
            state.get('slow_window_reason',''),
            state.get('slow_window_anchor_id',''),
            int(bool(state.get('scene_pan_active',False))),
            int(bool(state.get('scene_pan_raw_stable',False))),
            int(bool(state.get('scene_pan_stable',False))),
            int(bool(state.get('game_progress_scroll_active',False))),
            int(bool(state.get('game_progress_scroll_settling',False))),
            int(bool(state.get('game_progress_scroll_context',False))),
            int(state.get('game_progress_scroll_count',0)),
            float(state.get('game_progress_scroll_age',0.0)),
            int(bool(state.get('fullscreen_reframe_active',False))),
            int(state.get('fullscreen_reframe_count',0)),
            float(state.get('fullscreen_reframe_shift_px',0.0)),
            float(state.get('fullscreen_reframe_shift_lanes',0.0)),
            float(state.get('fullscreen_reframe_age',0.0)),
            int(bool(state.get('raw_scene_pan_ignored',False))),
            float(state.get('scene_shift_px',0.0)),
            float(state.get('scene_pan_score',0.0)),
            int(state.get('scene_pan_count',0)),
            float(state.get('motion_mog_ratio',0.0)),
            float(state.get('motion_diff_ratio',0.0)),
            int(bool(state.get('motion_ready',False))),
            float(state.get('motion_activity_risk',0.0)),
            float(state.get('lane_history_difficulty_score',0.0)),
            float(state.get('live_traffic_difficulty_score',0.0)),
            float(state.get('live_speed_difficulty_score',0.0)),
            float(state.get('live_density_difficulty_score',0.0)),
            str(state.get('difficulty_mode','NORMAL')),
            float(state.get('difficulty_mode_score',0.5)),
            float(state.get('difficulty_mode_raw_score',0.5)),
            str(state.get('difficulty_mode_candidate','NORMAL')),
            float(state.get('difficulty_mode_candidate_age',0.0)),
            float(state.get('difficulty_mode_age',0.0)),
            int(state.get('difficulty_mode_switches',0)),
            str(state.get('difficulty_mode_reason','')),
            str(state.get('difficulty_mode_floor','EASY')),
            float(state.get('difficulty_gap_score',0.5)),
            float(state.get('difficulty_speed_score',0.5)),
            float(state.get('difficulty_density_score',0.5)),
            int(state.get('motion_gap_support',0)),
            '' if state.get('motion_gap_p25') is None else float(state.get('motion_gap_p25')),
            '' if state.get('motion_gap_median') is None else float(state.get('motion_gap_median')),
            float(state.get('motion_busy_fraction',0.0)),
            float(state.get('source_failure_eta_floor',0.0)),
            float(state.get('source_reliability_eta_penalty',0.0)),
            int(bool(state.get('czn_live_ready',False))),
            float(state.get('czn_live_speed_reference',0.0)),
            '' if state.get('czn_historical_speed_p95') is None else float(state.get('czn_historical_speed_p95')),
            int(bool(state.get('czn_historical_prior_applied',False))),
            str(state.get('czn_speed_reference_source','')),
            int(state.get('czn_live_speed_support',0)),
            int(state.get('czn_session_speed_support',0)),
            float(state.get('czn_session_speed_guard_reference',0.0)),
            float(state.get('czn_observed_clear_speed_reference',0.0)),
            float(state.get('czn_stage_speed_reference',0.0)),
            int(bool(state.get('motion_live_ready',False))),
            float(state.get('motion_current_clear_elapsed',0.0)),
            '' if state.get('motion_preceding_busy_duration') is None else float(state.get('motion_preceding_busy_duration')),
            int(state.get('motion_slow_support',0)),
            '' if state.get('motion_slow_p25') is None else float(state.get('motion_slow_p25')),
            '' if state.get('motion_slow_median') is None else float(state.get('motion_slow_median')),
            '' if state.get('motion_slow_eta') is None else float(state.get('motion_slow_eta')),
            '' if state.get('motion_slow_required_eta') is None else float(state.get('motion_slow_required_eta')),
            state.get('target_lane_locked',''),
            float(state.get('target_lane_x',0.0)),
            int(state.get('target_lane_switches',0)),
            int(bool(state.get('target_lane_geometry_ok',False))),
            '' if state.get('target_lane_distance') is None else float(state.get('target_lane_distance')),
            '' if state.get('target_lane_distance_ratio') is None else float(state.get('target_lane_distance_ratio')),
            state.get('target_lane_lock_reason',''),
            int(state.get('target_lane_relocks',0)),
            int(bool(state.get('motion_slow_anchor_ok',False))),
            '' if state.get('motion_slow_anchor_age') is None else float(state.get('motion_slow_anchor_age')),
            '' if state.get('motion_slow_anchor_alignment') is None else float(state.get('motion_slow_anchor_alignment')),
            state.get('motion_slow_anchor_id',''),
            float(state.get('confirmed_slow_failure_floor',0.0)),
            '' if state.get('gap_open_eta') is None else float(state.get('gap_open_eta')),
            '' if state.get('gap_open_required_eta') is None else float(state.get('gap_open_required_eta')),
            '' if state.get('gap_open_remaining') is None else float(state.get('gap_open_remaining')),
            int(state.get('gap_open_support',0)),
            float(state.get('gap_open_confidence',0.0)),
            int(bool(state.get('gap_open_ready',False))),
            float(state.get('gap_open_failure_floor',0.0)),
            float(state.get('gap_open_source_rate',1.0)),
            int(state.get('manual_successes',0)),
            int(state.get('manual_failures',0)),
            int(state.get('manual_success_duplicate_skips',0)),
            int(state.get('last_manual_success_switch',-1)),
            int(state.get('manual_success_context_only',0)),
            int(bool(state.get('dynamic_gap_ready',False))),
            float(state.get('dynamic_gap_quantile',0.0)),
            '' if state.get('dynamic_gap_lower_bound') is None else float(state.get('dynamic_gap_lower_bound')),
            int(state.get('dynamic_gap_recent_support',0)),
            int(state.get('dynamic_gap_session_prior_support',0)),
            '' if state.get('dynamic_gap_session_prior_lower_bound') is None else float(state.get('dynamic_gap_session_prior_lower_bound')),
            int(bool(state.get('dynamic_gap_bootstrap_candidate',False))),
            int(bool(state.get('dynamic_gap_bootstrap_active',False))),
            '' if state.get('dynamic_gap_bootstrap_lower_bound') is None else float(state.get('dynamic_gap_bootstrap_lower_bound')),
            int(state.get('dynamic_gap_bootstrap_min_local_support',0)),
            float(state.get('dynamic_gap_required_eta',0.0)),
            '' if state.get('dynamic_gap_remaining') is None else float(state.get('dynamic_gap_remaining')),
            float(state.get('dynamic_gap_confidence',0.0)),
            int(state.get('dynamic_gap_mode_min_support',0)),
            float(state.get('dynamic_gap_mode_min_confidence',0.0)),
            float(state.get('dynamic_gap_mode_max_elapsed',0.0)),
            '' if state.get('dynamic_gap_recent_lower_bound') is None else float(state.get('dynamic_gap_recent_lower_bound')),
            '' if state.get('dynamic_gap_long_lower_bound') is None else float(state.get('dynamic_gap_long_lower_bound')),
            float(state.get('dynamic_gap_recent_weight',0.0)),
            str(state.get('dynamic_gap_regime_direction','')),
            float(state.get('dynamic_gap_failure_floor',0.0)),
            float(state.get('dynamic_gap_effective_failure_floor',0.0)),
            float(state.get('dynamic_gap_difficulty_credit',0.0)),
            float(state.get('dynamic_gap_source_rate',1.0)),
            float(state.get('dynamic_gap_pipeline_latency',0.0)),
            float(state.get('dynamic_gap_reaction_budget',0.0)),
            float(state.get('dynamic_gap_observed_action_delay',0.0)),
            '' if state.get('dynamic_gap_action_lease') is None else float(state.get('dynamic_gap_action_lease')),
            int(bool(state.get('dynamic_gap_czn_capped',False))),
            int(bool(state.get('czn_context_only',False))),
            float(state.get('dynamic_gap_lease_required',0.0)),
            float(state.get('dynamic_gap_effective_clear_elapsed',0.0)),
            int(state.get('late_reaction_observations',0)),
            float(state.get('dynamic_gap_mog_global_ratio',0.0)),
            int(state.get('dynamic_gap_preceding_busy_ok',0)),
            int(state.get('dynamic_gap_slow_guard',0)),
            int(state.get('chicken_forward_spike_rejected',0)),
            int(state.get('chicken_forward_spikes_rejected',0)),
            int(state.get('crash_forward_spikes_ignored',0)),
            float(state.get('scene_frame_activity',0.0)),
            int(state.get('stale_scene_watchdog',0)),
            int(state.get('stale_scene_recoveries',0)),
            int(state.get('landing_hold_recoveries',0)),
            int(state.get('forced_chicken_reacquires',0)),
            int(bool(state.get('post_jump_reacquire_active',False))),
            float(state.get('post_jump_reacquire_age_required',0.0)),
            float(state.get('landing_wait_age',0.0)),
            int(state.get('landing_wait_watchdog_recoveries',0)),
            int(bool(state.get('landing_wait_watchdog_recovered',False))),
            float(state.get('chicken_fresh_age',0.0)),
            int(bool(state.get('chicken_fresh',False))),
            int(state.get('chicken_candidate_count',0)),
            int(bool(state.get('chicken_midlane_rejected',False))),
            int(state.get('chicken_midlane_rejections',0)),
            float(state.get('runtime_tick_gap_seconds',0.0)),
            int(state.get('runtime_gap_recoveries',0)),
            int(bool(state.get('runtime_gap_recovery_active',False))),
            int(bool(state.get('tracking_starvation',False))),
            float(state.get('tracking_starvation_seconds',0.0)),
            int(bool(state.get('sensor_desync',False))),
            int(state.get('tracking_self_heals',0)),
            int(state.get('sensor_desync_heals',0)),
            int(bool(state.get('tracking_rewarm',False))),
            '' if state.get('target_proposal_x') is None else float(state.get('target_proposal_x')),
            '' if state.get('target_proposal_error_ratio') is None else float(state.get('target_proposal_error_ratio')),
            int(state.get('confirmed_jump_advances',0)),
            int(bool(state.get('slow_after_guard_active',False))),
            '' if state.get('recent_slow_pass_age') is None else float(state.get('recent_slow_pass_age')),
            float(state.get('v5_safe_probability',0.0)),
            float(state.get('v5_admission_threshold',0.0)),
            float(state.get('v5_effective_difficulty',0.0)),
            int(bool(state.get('v5_physical_override',False))),
            int(bool(state.get('v5_observed_clear_override',False))),
            float(state.get('v5_heuristic_probability',0.0)),
            '' if state.get('v5_longterm_probability') is None else float(state.get('v5_longterm_probability')),
            '' if state.get('v5_session_probability') is None else float(state.get('v5_session_probability')),
            int(state.get('v5_session_train_n',0)),
            int(state.get('v5_session_train_safe',0)),
            int(state.get('v5_session_train_unsafe',0)),
            int(bool(state.get('v5_raw_decision',False))),
            float(state.get('v5_commit_elapsed',0.0)),
            float(state.get('v5_commit_required',0.0)),
            int(bool(state.get('v5_committed',False))),
            float(state.get('v5_commit_age',0.0)),
            int(bool(state.get('v5_decision',False))),
            float(state.get('v5_failure_similarity',0.0)),
            int(state.get('v5_feedback_failures',0)),
            int(state.get('v5_feedback_successes',0)),
            int(state.get('green_signals',0)),
            int(state.get('green_acted',0)),
            int(state.get('green_active',0)),
            int(state.get('rearm_needed',0)),
            str(state.get('v5_gap_provenance','')),
            int(bool(state.get('v5_verified_gap_fastpath',False))),
            float(state.get('v5_verified_gap_action_lease',0.0)),
            float(state.get('v5_verified_gap_min_action_lease',0.0)),
            float(state.get('v5_verified_gap_physical_min_action_lease',0.0)),
            str(state.get('v5_verified_gap_lease_tier','')),
            float(state.get('v5_verified_gap_selected_lease_required',0.0)),
            int(state.get('v5_mode_physical_min_support',0)),
            float(state.get('v5_mode_physical_min_confidence',0.0)),
            float(state.get('v5_mode_physical_min_gap_p25',0.0)),
            float(state.get('v5_required_eta',0.0)),
            float(state.get('v5_historical_slow_after_risk',0.0)),
            '' if state.get('indicator_required_eta_override') is None else float(state.get('indicator_required_eta_override')),
            int(state.get('green_outcome_successes',0)),
            int(state.get('green_outcome_failures',0)),
            '' if state.get('visible_green_signal_id') is None else int(state.get('visible_green_signal_id')),
            '' if state.get('pending_green_signal_id') is None else int(state.get('pending_green_signal_id')),
            int(state.get('green_viewport_rebases',0)),
            float(state.get('analysis_anchor_x',0.0)),
            float(state.get('analysis_anchor_y',0.0)),
            int(bool(state.get('chicken_anchor_stable',False))),
            float(state.get('chicken_anchor_age',0.0)),
            float(state.get('chicken_anchor_dx',0.0)),
            '' if state.get('lane_phase_error_ratio') is None else float(state.get('lane_phase_error_ratio')),
            float(state.get('lane_phase_shift_px',0.0)),
            int(state.get('lane_phase_realigns',0)),
            int(state.get('lane_phase_realigns_suppressed',0)),
            float(state.get('lane_phase_bias_px',0.0)),
            str(state.get('lane_phase_sync_reason','')),
            int(bool(state.get('lane_phase_reanchored',False))),
            float(state.get('perf_capture_ms',0.0)),
            float(state.get('perf_chicken_ms',0.0)),
            float(state.get('perf_lane_ms',0.0)),
            float(state.get('perf_motion_ms',0.0)),
            float(state.get('perf_risk_ms',0.0)),
            float(state.get('perf_v5_ms',0.0)),
            float(state.get('perf_preoutcome_ms',0.0)),
            int(bool(state.get('performance_recovery_mode',False))),
            int(state.get('green_target_arrival_successes',0)),
            int(state.get('green_progress_handoffs',0)),
            int(state.get('green_rearm_geometry_releases',0)),
            *[state.get(k) for k in ('slow_window_profile_source', 'slow_window_follower_eta', 'slow_profile_recent_lane_support', 'slow_profile_recent_global_support', 'slow_profile_class_mismatches', 'slow_profile_directional_active', 'model_checkpoint_ok', 'model_checkpoint_ts', 'model_checkpoint_error')],
            *[state.get(k) for k in ('dynamic_gap_cycle_id', 'signal_admission_open', 'signal_admission_reason', 'green_missed_rearm_reason', 'green_missed_rearm_busy_cycle', 'green_missed_rearm_ready_cycle')],
            *[state.get(k) for k in ('runtime_tick_errors','runtime_tick_error_phase','runtime_tick_error_type')],
            *[state.get(k) for k in ('decision_frame_timestamp','green_display_deadline','green_display_expired','reset_candidate_pending','reset_confirmed_this_tick')],
            *[state.get(k) for k in ('upstream_arrival_eta','upstream_threat_id','upstream_required_seconds','upstream_prediction_available','upstream_prediction_blocked')],
            float(state.get('v5_degraded_lease_headroom',0.0)),
            float(state.get('v5_degraded_frame_margin',0.0)),
            int(bool(state.get('v5_sustained_observed_override',False))),
            int(bool(state.get('v5_active_green_hold_override',False))),
            float(state.get('v5_post_pass_settle_required',0.0)),
            float(state.get('v5_post_pass_clear_elapsed',0.0)),
            int(bool(state.get('v5_post_pass_ready',False))),
            *[state.get(k) for k in ('crossing_motion_available', 'crossing_motion_clear', 'crossing_motion_ratio', 'crossing_motion_reason', 'dynamic_gap_unlatched_lower_bound', 'detector_max_blob_area')],
        ])

    def learn_outcome(self, features, label, weight=1.0, source='generic'):
        """Balanced online classifier update.

        Class weighting is adjusted dynamically so repeated crash/unsafe labels
        cannot saturate the model at ~99% danger.
        """
        label = int(label)
        x = np.asarray([features], dtype=np.float64)
        y = np.asarray([label])

        own = self.unsafe_label_n if label == 1 else self.safe_label_n
        other = self.safe_label_n if label == 1 else self.unsafe_label_n
        balance = math.sqrt((other + 2.0) / (own + 2.0))
        balance = float(np.clip(balance, .45, 2.5))
        effective_weight = max(.05, float(weight) * balance)
        sw = np.asarray([effective_weight], dtype=np.float64)

        if not self.clf_ready:
            self.scaler.partial_fit(x)
            self.clf.partial_fit(
                self.scaler.transform(x), y,
                classes=np.asarray([0, 1]), sample_weight=sw
            )
            self.clf_ready = True
        else:
            self.scaler.partial_fit(x)
            self.clf.partial_fit(self.scaler.transform(x), y, sample_weight=sw)

        self.supervised_n += 1
        if label == 1:
            self.unsafe_label_n += 1
        else:
            self.safe_label_n += 1
        if source == 'geometry':
            self.geometry_label_n += 1


    @staticmethod
    def safety_context_from_state(state):
        """Compact decision context for crash-memory matching."""
        def f(key, default=0.0):
            try:
                v = state.get(key, default)
                if v is None:
                    return float(default)
                v = float(v)
                return float(default) if not np.isfinite(v) else v
            except Exception:
                return float(default)

        lane = state.get('lane', state.get('watch_lane_1', -1))
        try:
            lane = int(lane)
        except Exception:
            lane = -1

        return {
            'lane': lane,
            'source': str(state.get('eta_source', 'unknown') or 'unknown'),
            'eta': f('effective_eta', 0.0),
            'raw_risk': f('raw_risk', state.get('risk', 50.0)),
            'motion_ratio': f('motion_corridor_ratio', 1.0),
            'motion_dwell': f('motion_clear_dwell', 0.0),
            'clear_dwell': f('clear_dwell', 0.0),
            'czn_speed': f('czn_speed_reference', 0.0),
            'adaptive_conf': f('adaptive_confidence', 0.0),
            'gap25': f('regime_gap_p25', 1.25),
            'fast_frac': f('regime_fast_fraction', .33),
            'pattern_p25': f('current_pattern_p25', 0.0),
            'pattern_fast': f('current_pattern_p_next_fast', 1.0),
            'uncertain': f('uncertain_incoming_count', 0.0),
            'stage_score': f('stage_difficulty_score', 0.0),
        }

    def lane_difficulty_profile(self, lane):
        """Empirical stage difficulty; sparse stages borrow nearby evidence."""
        try:
            lane = int(lane)
        except Exception:
            lane = 0

        def lane_events(li):
            return [
                e for e in list(self.events.get(int(li), []))
                if e.get('token') != '<RESET>' and e.get('speed') is not None
            ]

        own = lane_events(lane)
        pooled = list(own)
        if len(pooled) < 8:
            for d in (1, 2):
                for li in (lane-d, lane+d):
                    if li >= 0:
                        pooled.extend(lane_events(li))
                    if len(pooled) >= 18:
                        break
                if len(pooled) >= 18:
                    break

        all_events = [
            e for hist in self.events.values()
            for e in list(hist)
            if e.get('token') != '<RESET>' and e.get('speed') is not None
        ]

        def speeds(ev):
            return np.asarray([
                float(e.get('speed', 0.0)) for e in ev
                if 10.0 <= float(e.get('speed', 0.0)) <= 900.0
            ], dtype=float)

        def gaps(ev):
            return np.asarray([
                float(e.get('gap')) for e in ev
                if e.get('gap') is not None
                and self.min_valid_gap_seconds <= float(e.get('gap')) <= self.max_valid_gap_seconds
            ], dtype=float)

        own_s, pool_s, global_s = speeds(own), speeds(pooled), speeds(all_events)
        own_g, pool_g, global_g = gaps(own), gaps(pooled), gaps(all_events)

        global_p95 = float(np.percentile(global_s,95)) if len(global_s) else 180.0
        pool_p95 = float(np.percentile(pool_s,95)) if len(pool_s) else global_p95
        own_p95 = float(np.percentile(own_s,95)) if len(own_s) >= 3 else pool_p95

        global_gap25 = float(np.percentile(global_g,25)) if len(global_g) else 1.0
        pool_gap25 = float(np.percentile(pool_g,25)) if len(pool_g) else global_gap25
        own_gap25 = float(np.percentile(own_g,25)) if len(own_g) >= 3 else pool_gap25

        speed_ref = max(global_p95, own_p95, pool_p95 * .95)
        speed_score = float(np.clip((speed_ref - 150.0) / 360.0, 0.0, 1.0))
        density_score = float(np.clip((1.05 - own_gap25) / .80, 0.0, 1.0))
        progress_score = float(np.clip(lane / 21.0, 0.0, 1.0))
        difficulty = float(np.clip(
            .55*speed_score + .30*density_score + .15*progress_score,
            0.0, 1.0
        ))

        return {
            'lane': lane,
            'support': len(own),
            'pooled_support': len(pooled),
            'speed_p95': float(own_p95),
            'pooled_speed_p95': float(pool_p95),
            'gap_p25': float(own_gap25),
            'speed_reference': float(speed_ref),
            'difficulty': difficulty,
        }

    @staticmethod
    def _context_distance(a, b):
        if not a or not b:
            return 9.0
        d = [0.0 if str(a.get('source')) == str(b.get('source')) else .65]
        scales = {
            'lane': 3.0, 'eta': .55, 'raw_risk': 30.0,
            'motion_ratio': .12, 'motion_dwell': 2.5, 'clear_dwell': 2.5,
            'czn_speed': 160.0, 'adaptive_conf': .16, 'gap25': .80,
            'fast_frac': .35, 'pattern_p25': .90, 'pattern_fast': .40,
            'uncertain': 2.0, 'stage_score': .35,
        }
        for k, sc in scales.items():
            av = float(a.get(k, 0.0) or 0.0)
            bv = float(b.get(k, 0.0) or 0.0)
            d.append(min(2.5, abs(av-bv)/max(1e-6, sc)))
        return float(np.sqrt(np.mean(np.square(d))))

    def crash_memory_score(self, context):
        if not context or not self.crash_memory:
            return {'score':0.0,'crash_similarity':0.0,'safe_similarity':0.0,'matches':0}

        now=time.time()
        crash_sims = []
        for p in self.crash_memory:
            dist = self._context_distance(context, p.get('context', {}))
            w = float(p.get('weight', .6))
            age=max(0.0,now-float(p.get('timestamp',now)))
            decay=0.5 ** (age/max(60.0,self.crash_memory_half_life))
            crash_sims.append(
                w * decay *
                math.exp(-(dist*dist)/(2*self.crash_memory_sigma*self.crash_memory_sigma))
            )

        safe_sims = []
        for p in self.safe_memory:
            dist = self._context_distance(context, p.get('context', {}))
            w = float(p.get('weight', .7))
            safe_sims.append(
                w * math.exp(-(dist*dist)/(2*self.crash_memory_sigma*self.crash_memory_sigma))
            )

        c = max(crash_sims) if crash_sims else 0.0
        s = max(safe_sims) if safe_sims else 0.0
        score = float(np.clip(c - .55*s, 0.0, 1.0))
        return {
            'score':score, 'crash_similarity':float(c),
            'safe_similarity':float(s),
            'matches':int(sum(v >= .55 for v in crash_sims))
        }

    def remember_crash_context(self, context, timestamp=None, weight=.65, source='missed_crash'):
        if context:
            self.crash_memory.append({
                'timestamp':float(timestamp or time.time()),
                'weight':float(np.clip(weight,.20,1.0)),
                'source':str(source), 'context':dict(context)
            })

    def remember_safe_context(self, context, timestamp=None, weight=.70, source='green_success'):
        if context:
            self.safe_memory.append({
                'timestamp':float(timestamp or time.time()),
                'weight':float(np.clip(weight,.20,1.0)),
                'source':str(source), 'context':dict(context)
            })

    def learn_manual_lane_success(self, state, timestamp=None):
        """Learn a real successful lane transition without a model GREEN.

        This uses an actual completed target-lane ARRIVED transition. It is
        lower-weight than a validated GREEN success because exact click time is
        unknown, but unlike old counterfactual SAFE labels the chicken really
        did complete the jump.
        """
        if not state:
            return 0
        feat=state.get('training_features')
        if feat is None:
            return 0

        ts=float(timestamp or time.time())
        ctx=self.safety_context_from_state(state)
        if ctx:
            self.remember_safe_context(
                ctx,timestamp=ts,weight=.55,
                source='manual_lane_success'
            )
        self.learn_outcome(
            feat,0,weight=.65,source='manual_lane_success'
        )
        return 1

    def learn_manual_lane_failure(self, attempt, timestamp=None):
        """Learn an actual failed manual jump captured at action onset."""
        if not attempt:
            return 0
        feat=attempt.get('features')
        ctx=attempt.get('context')
        ts=float(timestamp or time.time())
        if ctx:
            self.remember_crash_context(
                ctx,timestamp=ts,weight=.82,
                source='manual_jump_failure'
            )
        if feat is not None:
            self.learn_outcome(
                feat,1,weight=.90,source='manual_jump_failure'
            )
            return 1
        return 0


    def record_causal_late_green_failure(self, attempt, timestamp=None):
        """Learn source reliability from a late GREEN reaction that actually crashes.

        This is intentionally narrower than record_green_outcome(): the late
        signal does not become a supervised GREEN feature label, but an actual
        unresolved jump that was triggered shortly after that GREEN and then
        crashed is valid evidence that the source/ETA was too optimistic.
        """
        if not attempt or not attempt.get('late_after_green'):
            return 0
        try:
            delay=float(attempt.get('late_green_delay'))
        except Exception:
            return 0
        max_delay=float(self.late_green_causal_max_seconds)
        if not np.isfinite(delay) or delay < 0 or delay > max_delay:
            return 0

        src=str(attempt.get('late_green_source','unknown') or 'unknown')
        lane=attempt.get('late_green_lane')
        lane_src=self._source_lane_key(src,lane)
        self.green_failure_n += 1
        self.green_source_failures[src] += 1
        self.green_source_failures[lane_src] += 1
        try:
            eta=float(attempt.get('late_green_eta'))
            if np.isfinite(eta) and eta > 0:
                self.green_source_failure_etas[src].append(eta)
                self.green_source_failure_etas[lane_src].append(eta)
        except Exception:
            pass
        return 1


    def learn_crash_window(self, samples, crash_event):
        """Learn a bounded number of unsafe pre-crash states."""
        if not samples:
            return 0

        event_time = float(crash_event.get('event_time', time.time()))
        valid = [x for x in samples if x.get('features') is not None]
        if not valid:
            return 0

        n = min(self.max_crash_samples_per_event, len(valid))
        if n < len(valid):
            idx = np.linspace(0, len(valid)-1, n).astype(int)
            chosen = [valid[i] for i in idx]
        else:
            chosen = valid

        used = 0
        for item in chosen:
            age = max(0.0, event_time - float(item.get('timestamp', event_time)))
            ctx = item.get('safety_context')
            raw = float(item.get('raw_risk', 50.0))

            # A generic crash may be the result of a manual jump the model never
            # recommended.  Treating every such crash as supervised UNSAFE
            # poisoned earlier versions with hundreds of negative labels.
            #
            # GREEN-attributed failures are learned separately by
            # record_green_outcome() and retain full supervised weight.
            if ctx and raw <= 30.0:
                self.remember_crash_context(
                    ctx, timestamp=event_time,
                    weight=min(.35, .22 + .10*max(0.0,1.0-age/2.0)),
                    source='general_missed_crash'
                )
            used += 1

        if used:
            self.crash_count += 1
            self.crash_sample_n += used
            exists = self.crash_log_path.exists()
            with self.crash_log_path.open('a', newline='') as f:
                w = csv.writer(f)
                if not exists:
                    w.writerow([
                        'timestamp','reason','samples','lane','raw_risk',
                        'display_risk','pattern','start_x','max_x','reset_x'
                    ])
                last = chosen[-1]
                w.writerow([
                    event_time, crash_event.get('reason','unknown'), used,
                    last.get('lane','-'), last.get('raw_risk',''),
                    last.get('display_risk',''), last.get('pattern',''),
                    crash_event.get('start_x',''), crash_event.get('max_x',''),
                    crash_event.get('reset_x','')
                ])
        return used


    def record_green_outcome(self, outcome):
        """Learn only from causally observed ONE-JUMP GREEN outcomes."""
        if not outcome or outcome.get('outcome') not in ('success', 'failure'):
            return 0
        # V5.3.8 defense-in-depth: legacy crash-progress fallback and any event
        # already identified as multi-jump/unvalidated can never train GREEN.
        if (
            bool(outcome.get('weak_action_attribution', False))
            or str(outcome.get('attribution','')) == 'crash_progress_fallback'
            or outcome.get('one_jump_valid') is False
        ):
            return 0

        status = str(outcome['outcome'])

        action_delay=None
        src_for_delay=str(
            outcome.get('timing_source', outcome.get('eta_source','unknown'))
        )
        try:
            if outcome.get('action_start_ts') is not None:
                action_delay=(
                    float(outcome.get('action_start_ts'))
                    - float(outcome.get(
                        'start_ts',outcome.get('action_start_ts')
                    ))
                )
                if not (np.isfinite(action_delay) and .05 <= action_delay <= 3.0):
                    action_delay=None
        except Exception:
            action_delay=None

        # IMPORTANT: do not train the user's reaction-time budget from failed
        # jumps. Purposeful crash training and animation/detection latency made
        # old V5 builds interpret failures as a slow user, which then starved
        # GREEN. Only a validated successful action is reaction-time evidence.
        if (
            status == 'success'
            and action_delay is not None and action_delay <= 2.8
            and not bool(outcome.get('synthetic_progress_handoff',False))
        ):
            self.green_source_action_delays[src_for_delay].append(float(action_delay))
            self.green_source_action_delays['__all__'].append(float(action_delay))

        late_execution=False
        try:
            late_execution=bool(
                status=='failure'
                and not (
                    outcome.get('input_owned')
                    and outcome.get('input_movement_seen')
                    and outcome.get('attribution') == 'recorded_space_input'
                    and outcome.get('input_validated_deadline') is not None
                    and float(outcome.get('action_start_ts',float('inf'))) <
                        float(outcome['input_validated_deadline'])
                )
                and outcome.get('action_start_ts') is not None
                and outcome.get('end_ts') is not None
                and float(outcome.get('action_start_ts'))
                    > float(outcome.get('end_ts'))+.04
            )
        except Exception:
            late_execution=False

        post_green_delay=0.0
        try:
            if outcome.get('post_green_delay') is not None:
                post_green_delay=max(0.0,float(outcome.get('post_green_delay')))
            elif late_execution:
                post_green_delay=max(0.0,
                    float(outcome.get('action_start_ts'))-float(outcome.get('end_ts'))
                )
        except Exception:
            post_green_delay=0.0
        attribution=str(outcome.get('attribution','') or '')
        causal_late_failure=bool(
            late_execution
            and post_green_delay <= float(self.late_green_causal_max_seconds)
            and attribution in ('post_green_grace','green_active')
        )
        failure_type=(
            'delayed_confirmation_failure' if causal_late_failure
            else ('unattributed_delayed_failure' if late_execution else 'hazard_failure')
        )

        ts = float(outcome.get('outcome_ts', time.time()))
        speed_pattern = str(outcome.get('speed_pattern', '-') or '-')
        type_pattern = str(outcome.get('type_pattern', '-') or '-')
        features = outcome.get('features')

        eta_source = str(outcome.get('eta_source', 'unknown'))
        attribution_conf = float(np.clip(
            outcome.get('attribution_confidence', 1.0), .25, 1.0
        ))
        training_eligible = True
        training_skip_reason = ''
        if (
            eta_source in ('clear-zone', 'fused')
            and not bool(outcome.get('czn_calibrated', False))
        ):
            training_eligible = False
            training_skip_reason = 'uncalibrated_czn'

        context = outcome.get('safety_context')

        if status == 'success':
            self.green_success_n += 1
            if context is not None:
                self.remember_safe_context(
                    context, timestamp=ts,
                    weight=.55 + .25*attribution_conf,
                    source='acted_green_success'
                )
            self.green_speed_successes[speed_pattern] += 1
            src = str(outcome.get('timing_source', outcome.get('eta_source','unknown')))
            lane_src = self._source_lane_key(src, outcome.get('lane'))
            self.green_source_successes[src] += 1
            self.green_source_successes[lane_src] += 1
            if features is not None and training_eligible:
                self.learn_outcome(
                    features, 0,
                    weight=self.outcome_success_weight * attribution_conf,
                    source='green_success'
                )
        else:
            self.green_failure_n += 1
            src=str(outcome.get('timing_source', outcome.get('eta_source','unknown')))
            lane_src=self._source_lane_key(src,outcome.get('lane'))

            # V5.2.1 BUG: every post-GREEN failure was logged, then excluded
            # from source/supervised learning merely because visible chicken
            # movement was detected after the display changed from GREEN. The
            # outcome tracker has already proven causal attribution by keeping
            # the signal inside post_green_action_grace; learn it, with reduced
            # weight, instead of throwing away the user's deliberate failures.
            if late_execution and not causal_late_failure:
                self.green_source_late_failures[src] += 1
                training_eligible=False
                training_skip_reason='late_outside_causal_window'
            else:
                if late_execution:
                    self.green_source_late_failures[src] += 1
                late_scale=(
                    float(np.clip(.82-.12*post_green_delay,.55,.82))
                    if causal_late_failure else 1.0
                )
                if context is not None:
                    self.remember_crash_context(
                        context,timestamp=ts,
                        weight=(.65+.35*attribution_conf)*late_scale,
                        source=(
                            'acted_green_failure_late_causal'
                            if causal_late_failure else 'acted_green_failure'
                        )
                    )
                self.green_speed_failures[speed_pattern] += 1
                self.green_pattern_failures[speed_pattern] += 1
                self.green_source_failures[src] += 1
                self.green_source_failures[lane_src] += 1
                try:
                    fail_eta=float(outcome.get('eta'))
                    if np.isfinite(fail_eta) and fail_eta>0:
                        self.green_source_failure_etas[src].append(fail_eta)
                        self.green_source_failure_etas[lane_src].append(fail_eta)
                except Exception:
                    pass
                if features is not None and training_eligible:
                    self.learn_outcome(
                        features,1,
                        weight=self.outcome_failure_weight*attribution_conf*late_scale,
                        source=(
                            'green_failure_late_causal'
                            if causal_late_failure else 'green_failure'
                        )
                    )

        exists = self.green_outcome_log_path.exists()
        with self.green_outcome_log_path.open('a', newline='') as f:
            w = csv.writer(f)
            if not exists:
                w.writerow([
                    'outcome_timestamp','signal_id','outcome','green_start','green_end',
                    'green_duration','action_start','action_delay','lane','eta_source',
                    'eta','raw_risk','display_risk','speed_pattern','type_pattern',
                    'pattern_support','pattern_confidence','expected_gap','p25_gap',
                    'p_next_slow','p_next_medium','p_next_fast','baseline_x',
                    'action_start_x','end_x','forward_dx','crash_reason',
                    'czn_calibrated','czn_confirmed_events','czn_required_events',
                    'czn_unique_raw_tracks','czn_calibration_mode',
                    'czn_speed_reference','adaptive_confidence',
                    'adaptive_required_confidence','regime_id','regime_samples',
                    'training_eligible','training_skip_reason','failure_type',
                    'outcome_state','landing_source'
                ])
            w.writerow([
                ts, outcome.get('signal_id',''), status,
                outcome.get('start_ts',''), outcome.get('end_ts',''),
                outcome.get('duration',''), outcome.get('action_start_ts',''),
                '' if outcome.get('action_start_ts') is None else
                    float(outcome.get('action_start_ts')) - float(outcome.get('start_ts', outcome.get('action_start_ts'))),
                outcome.get('lane',''), outcome.get('eta_source','unknown'),
                outcome.get('eta',''), outcome.get('raw_risk',''),
                outcome.get('display_risk',''), speed_pattern, type_pattern,
                outcome.get('pattern_support',''), outcome.get('pattern_confidence',''),
                outcome.get('expected_gap',''), outcome.get('p25_gap',''),
                outcome.get('p_next_slow',''), outcome.get('p_next_medium',''),
                outcome.get('p_next_fast',''), outcome.get('baseline_x',''),
                outcome.get('action_start_x',''), outcome.get('end_x',''),
                outcome.get('forward_dx',''), outcome.get('crash_reason',''),
                int(bool(outcome.get('czn_calibrated', False))),
                outcome.get('czn_confirmed_events',''),
                outcome.get('czn_required_events',''),
                outcome.get('czn_unique_raw_tracks',''),
                outcome.get('czn_calibration_mode',''),
                outcome.get('czn_speed_reference',''),
                outcome.get('adaptive_confidence',''),
                outcome.get('adaptive_required_confidence',''),
                outcome.get('regime_id',''), outcome.get('regime_samples',''),
                int(bool(training_eligible)), training_skip_reason,
                (failure_type if status=='failure' else ''),
                outcome.get('outcome_state',''),outcome.get('landing_source','')
            ])

        if status == 'failure':
            exists = self.green_failure_log_path.exists()
            with self.green_failure_log_path.open('a', newline='') as f:
                w = csv.writer(f)
                if not exists:
                    w.writerow([
                        'outcome_timestamp','signal_id','green_start','action_start',
                        'lane','eta_source','eta','raw_risk','display_risk',
                        'speed_pattern','type_pattern','pattern_support',
                        'pattern_confidence','forward_dx','crash_reason',
                        'czn_calibrated','czn_confirmed_events',
                        'czn_speed_reference','training_eligible',
                        'training_skip_reason','failure_type'
                    ])
                w.writerow([
                    ts, outcome.get('signal_id',''), outcome.get('start_ts',''),
                    outcome.get('action_start_ts',''), outcome.get('lane',''),
                    outcome.get('eta_source','unknown'), outcome.get('eta',''),
                    outcome.get('raw_risk',''), outcome.get('display_risk',''),
                    speed_pattern, type_pattern, outcome.get('pattern_support',''),
                    outcome.get('pattern_confidence',''), outcome.get('forward_dx',''),
                    outcome.get('crash_reason','unknown'),
                    int(bool(outcome.get('czn_calibrated', False))),
                    outcome.get('czn_confirmed_events',''),
                    outcome.get('czn_speed_reference',''),
                    int(bool(training_eligible)), training_skip_reason,
                    failure_type
                ])
        return 1 if training_eligible else 0

    def green_failure_penalty(self, speed_pattern):
        key = str(speed_pattern or '-')
        # '-' means there was no validated traffic sequence. Penalizing this key
        # globally made every later lane inherit the same failures. Source ETA
        # learning and crash memory handle those outcomes instead.
        if key in ('-', '', 'unknown', 'None'):
            return 0.0
        fails = int(self.green_speed_failures.get(key, 0))
        succ = int(self.green_speed_successes.get(key, 0))
        acted = fails + succ
        if fails <= 0:
            return 0.0
        fail_rate = fails / acted if acted else 1.0
        base = 3.0 if fails == 1 else 6.0 + 2.0 * (fails - 2)
        return float(min(14.0, base * max(.35, fail_rate)))

    def record_late_action_observation(self, event):
        """Record a late post-GREEN movement as DIAGNOSTIC timing only.

        V4.4.6 fed these observations into the reaction budget.  In the latest
        logs the six late observations were 1.40-1.79 s and drove RT to its
        0.72 s ceiling even though they can simply be unrelated manual moves
        after a GREEN the user ignored.  Only an action actually attributed to
        a GREEN outcome is allowed to train the gating reaction budget now.
        """
        if not event:
            return 0

        src=str(event.get('eta_source','unknown'))
        delay=event.get('action_delay_from_start')
        if delay is None:
            return 0
        try:
            delay=float(delay)
        except Exception:
            return 0

        if not np.isfinite(delay) or delay < .05 or delay > 1.80:
            return 0

        self.green_source_late_action_delays[src].append(delay)
        self.green_source_late_action_delays['__all__'].append(delay)
        self.green_late_action_observations[src] += 1
        self.green_late_action_observations['__all__'] += 1
        return 1

    def source_action_delay_budget(
        self, eta_source, default=.38, min_delay=.24, max_delay=.72
    ):
        """Adaptive user-response budget for an actionable GREEN."""
        src=str(eta_source or 'unknown')
        vals=[
            float(v) for v in self.green_source_action_delays.get(src,[])
            if v is not None and np.isfinite(float(v))
            and .05 <= float(v) <= 2.8
        ]
        if not vals:
            vals=[
                float(v) for v in self.green_source_action_delays.get('__all__',[])
                if v is not None and np.isfinite(float(v))
                and .05 <= float(v) <= 2.8
            ]
        default=float(default)
        if not vals:
            return float(np.clip(default,min_delay,max_delay))
        arr=np.asarray(vals[-20:],dtype=float)
        robust=float(np.percentile(arr,55))
        n=min(8,len(arr))
        # Five-sample prior: learn genuine repeated latency without allowing one
        # very late action to starve all future opportunities.
        blended=(5.0*default+n*robust)/(5.0+n)
        return float(np.clip(blended+.04,min_delay,max_delay))

    def source_failure_eta_floor(self, eta_source, lane=None, base=0.0):
        """Learn a conservative ETA floor from acted failures.

        CZN failures in the latest run clustered tightly at ~1.44 s. A source
        that has already failed at an ETA should not keep authorizing the same
        ETA. The floor is source-global because local lane IDs are reused when
        the viewport pans. Lane-specific failures may only raise it further.
        """
        src = str(eta_source or 'unknown')
        vals = list(self.green_source_failure_etas.get(src, []))
        if lane is not None:
            vals += list(self.green_source_failure_etas.get(
                self._source_lane_key(src, lane), []
            ))
        vals = [float(v) for v in vals if v is not None and np.isfinite(float(v)) and float(v) > 0]
        if len(vals) < int(getattr(self, 'failure_eta_min_samples', 2)):
            return float(base)
        # Upper-quartile/maximum-like behavior without allowing one corrupt ETA
        # to set an extreme permanent floor.
        q = float(np.percentile(np.asarray(vals, dtype=float), 85))
        return float(max(float(base), q + self.failure_eta_margin))


    @staticmethod
    def _source_lane_key(eta_source, lane=None):
        source = str(eta_source or 'unknown')
        if lane is None:
            return source
        try:
            return f"{source}|L{int(lane)}"
        except Exception:
            return source

    def green_source_reliability(self, eta_source, lane=None):
        """Lane-local reliability with a weak global prior."""
        source = str(eta_source or 'unknown')
        lane_key = self._source_lane_key(source, lane)

        gs = int(self.green_source_successes.get(source, 0))
        gf = int(self.green_source_failures.get(source, 0))
        gn = gs + gf
        global_rate = (gs + 4.0) / (gn + 5.0)

        ls = int(self.green_source_successes.get(lane_key, 0))
        lf = int(self.green_source_failures.get(lane_key, 0))
        ln = ls + lf
        lane_rate = (ls + 4.0) / (ln + 5.0)

        if lane is None:
            rate = global_rate
        elif ln == 0:
            rate = .80*0.80 + .20*global_rate
        elif ln == 1:
            rate = .75*lane_rate + .25*global_rate
        else:
            rate = .85*lane_rate + .15*global_rate

        return {
            'attempts': ln if lane is not None else gn,
            'successes': ls if lane is not None else gs,
            'failures': lf if lane is not None else gf,
            'rate': float(np.clip(rate, 0.0, 1.0)),
            'lane_attempts': int(ln),
            'lane_rate': float(lane_rate),
            'global_attempts': int(gn),
            'global_rate': float(global_rate),
            'key': lane_key,
        }


    def predict_danger(self, features):
        lo = min(self.safe_label_n, self.unsafe_label_n)
        hi = max(self.safe_label_n, self.unsafe_label_n)
        imbalance = float(hi) / max(1.0, float(lo))
        if (
            not self.clf_ready
            or self.safe_label_n < self.min_balanced_class_samples
            or self.unsafe_label_n < self.min_balanced_class_samples
            or imbalance > self.max_supervised_class_imbalance
        ):
            return None
        try:
            x = np.asarray([features], dtype=np.float64)
            return float(self.clf.predict_proba(self.scaler.transform(x))[0, 1])
        except Exception:
            return None

    def flush(self, save_model=True):
        if self.rows:
            exists = self.path.exists()
            with self.path.open('a', newline='') as f:
                w = csv.writer(f)
                if not exists:
                    w.writerow(['timestamp','track_id','lane','cx','cy','vx','vy','speed','accel','width','height','mean_h','mean_s','mean_v'])
                w.writerows(self.rows)
            self.rows.clear()
        if self.event_rows:
            exists = self.event_log_path.exists()
            with self.event_log_path.open('a', newline='') as f:
                w = csv.writer(f)
                if not exists:
                    w.writerow(['timestamp','lane','track_id','token','speed_class','vehicle_type','speed','vx','vy','gap_from_previous','track_age','vertical_displacement'])
                w.writerows(self.event_rows)
            self.event_rows.clear()

        if self.state_rows:
            exists = self.state_log_path.exists()
            with self.state_log_path.open('a', newline='') as f:
                w = csv.writer(f)
                if not exists:
                    w.writerow([
                        'timestamp','chicken_x','chicken_y','watch_lane_1','watch_lane_2',
                        'raw_risk','display_risk','risk_mean','risk_std','risk_max',
                        'indicator_state','green_confirmed','visible_threat','threat_track_id',
                        'threat_tti','safe_window','lane1_direct_risk','lane1_pattern_risk',
                        'lane1_ml_risk','lane2_risk','pattern_text','active_tracks',
                        'crash_event','crash_reason','crashes_learned','crash_samples',
                        'pattern_events','ml_samples','eta_gate_ok','clear_eta',
                        'clear_block_reason','eta_source_for_gate','required_clear_eta',
                        'pattern_support','pattern_confidence',
                        'pattern_source','pattern_expected_gap','pattern_remaining',
                        'eta_source','direct_eta','pattern_eta','clear_zone_eta',
                        'clear_zone_direction','clear_zone_distance','effective_eta',
                        'chicken_position_confirmed','chicken_position_pending',
                        'p_next_slow','p_next_medium','p_next_fast',
                        'slow_after_gap_score','green_failure_penalty',
                        'green_failures_learned','green_successes_learned',
                        'safe_labels','unsafe_labels','ml_adjustment',
                        'speed_pattern_sequence','candidate_pattern',
                        'candidate_validated','pattern_green_success_rate',
                        'lane_visibility_ok','lane_visibility_score','lane_mean_gray',
                        'lane_dark_ratio','clear_dwell','recent_threat_age',
                        'pattern_p25_remaining','pattern_guard_ok','green_evidence_ok',
                        'green_evidence_reason','eta_source_reliability',
                        'eta_source_attempts','green_required_eta',
                        'regime_id','regime_samples','regime_reason',
                        'adaptive_confidence','adaptive_required_confidence',
                        'adaptive_required_dwell','regime_speed_p90',
                        'regime_gap_p25','regime_gap_cv','regime_fast_fraction',
                        'recent_regime_crashes','recent_green_successes',
                        'recent_green_failures','recent_green_reliability',
                        'green_late_unattributed','post_green_action_grace',
                        'czn_calibrated','czn_confirmed_events',
                        'czn_required_events','czn_raw_speed_samples',
                        'czn_unique_raw_tracks','czn_required_unique_tracks',
                        'czn_calibration_mode','czn_calibration_age',
                        'czn_event_speed_p95','czn_raw_speed_p95',
                        'czn_speed_reference',
                        'uncertain_incoming_count','current_pattern_support',
                        'current_pattern_p25','current_pattern_p_next_fast',
                        'evidence_stable_elapsed','evidence_stable_required',
                        'evidence_ready','motion_corridor_available',
                        'motion_corridor_clear','motion_corridor_ratio',
                        'motion_clear_dwell','stage_difficulty_score',
                        'stage_profile_support','stage_speed_p95',
                        'stage_gap_p25','stage_speed_reference',
                        'crash_memory_score','crash_memory_matches',
                        'crash_memory_safe_similarity','processing_fps',
                        'processing_lag_ms','processing_healthy',
                        'processing_degraded','processing_green_floor_fps',
                        'tracking_roi_lane','tracking_roi_area_pct',
                        'tracking_roi_fallback_hold','tracking_roi_fallback_holds',
                        'two_lane_learning','lookahead_lane','lookahead_risk',
                        'lookahead_candidate_count','lookahead_visible_threat',
                        'lookahead_clear_dwell','lookahead_motion_clear_dwell',
                        'lookahead_motion_ratio','lookahead_stage_difficulty',
                        'lookahead_stage_speed_p95',
                        'slow_window_mode','slow_window_profile_support',
                        'slow_window_lane_support','slow_window_profile_confidence',
                        'slow_window_p_fast','slow_window_p25_gap',
                        'slow_window_median_gap','slow_window_eta',
                        'slow_window_required_eta','slow_window_reason',
                        'slow_window_anchor_id',
                        'scene_pan_active','scene_pan_raw_stable','scene_pan_stable',
                        'game_progress_scroll_active','game_progress_scroll_settling',
                        'game_progress_scroll_context','game_progress_scroll_count',
                        'game_progress_scroll_age',
                        'fullscreen_reframe_active','fullscreen_reframe_count',
                        'fullscreen_reframe_shift_px','fullscreen_reframe_shift_lanes',
                        'fullscreen_reframe_age','raw_scene_pan_ignored',
                        'scene_shift_px',
                        'scene_pan_score','scene_pan_count',
                        'motion_mog_ratio','motion_diff_ratio','motion_ready',
                        'motion_activity_risk',
                        'lane_history_difficulty_score',
                        'live_traffic_difficulty_score',
                        'live_speed_difficulty_score',
                        'live_density_difficulty_score',
                        'difficulty_mode','difficulty_mode_score',
                        'difficulty_mode_raw_score','difficulty_mode_candidate',
                        'difficulty_mode_candidate_age','difficulty_mode_age',
                        'difficulty_mode_switches','difficulty_mode_reason',
                        'difficulty_mode_floor',
                        'difficulty_gap_score','difficulty_speed_score',
                        'difficulty_density_score',
                        'motion_gap_support','motion_gap_p25','motion_gap_median',
                        'motion_busy_fraction','source_failure_eta_floor',
                        'source_reliability_eta_penalty','czn_live_ready',
                        'czn_live_speed_reference','czn_historical_speed_p95',
                        'czn_historical_prior_applied','czn_speed_reference_source',
                        'czn_live_speed_support','czn_session_speed_support',
                        'czn_session_speed_guard_reference',
                        'czn_observed_clear_speed_reference',
                        'czn_stage_speed_reference',
                        'motion_live_ready','motion_current_clear_elapsed',
                        'motion_preceding_busy_duration','motion_slow_support',
                        'motion_slow_p25','motion_slow_median','motion_slow_eta',
                        'motion_slow_required_eta','target_lane_locked',
                        'target_lane_x','target_lane_switches',
                        'target_lane_geometry_ok','target_lane_distance',
                        'target_lane_distance_ratio','target_lane_lock_reason',
                        'target_lane_relocks','motion_slow_anchor_ok',
                        'motion_slow_anchor_age','motion_slow_anchor_alignment',
                        'motion_slow_anchor_id','confirmed_slow_failure_floor',
                        'gap_open_eta','gap_open_required_eta','gap_open_remaining',
                        'gap_open_support','gap_open_confidence','gap_open_ready',
                        'gap_open_failure_floor','gap_open_source_rate',
                        'manual_successes','manual_failures',
                        'manual_success_duplicate_skips',
                        'last_manual_success_switch',
                        'manual_success_context_only',
                        'dynamic_gap_ready','dynamic_gap_quantile',
                        'dynamic_gap_lower_bound','dynamic_gap_recent_support',
                        'dynamic_gap_session_prior_support',
                        'dynamic_gap_session_prior_lower_bound',
                        'dynamic_gap_bootstrap_candidate',
                        'dynamic_gap_bootstrap_active',
                        'dynamic_gap_bootstrap_lower_bound',
                        'dynamic_gap_bootstrap_min_local_support',
                        'dynamic_gap_required_eta','dynamic_gap_remaining',
                        'dynamic_gap_confidence','dynamic_gap_mode_min_support',
                        'dynamic_gap_mode_min_confidence','dynamic_gap_mode_max_elapsed',
                        'dynamic_gap_recent_lower_bound','dynamic_gap_long_lower_bound',
                        'dynamic_gap_recent_weight','dynamic_gap_regime_direction',
                        'dynamic_gap_failure_floor',
                        'dynamic_gap_effective_failure_floor',
                        'dynamic_gap_difficulty_credit',
                        'dynamic_gap_source_rate','dynamic_gap_pipeline_latency',
                        'dynamic_gap_reaction_budget',
                        'dynamic_gap_observed_action_delay',
                        'dynamic_gap_action_lease',
                        'dynamic_gap_czn_capped','czn_context_only',
                        'dynamic_gap_lease_required',
                        'dynamic_gap_effective_clear_elapsed',
                        'late_reaction_observations',
                        'dynamic_gap_mog_global_ratio',
                        'dynamic_gap_preceding_busy_ok',
                        'dynamic_gap_slow_guard',
                        'chicken_forward_spike_rejected',
                        'chicken_forward_spikes_rejected',
                        'crash_forward_spikes_ignored',
                        'scene_frame_activity','stale_scene_watchdog',
                        'stale_scene_recoveries','landing_hold_recoveries',
                        'forced_chicken_reacquires',
                        'post_jump_reacquire_active',
                        'post_jump_reacquire_age_required',
                        'landing_wait_age',
                        'landing_wait_watchdog_recoveries',
                        'landing_wait_watchdog_recovered',
                        'chicken_fresh_age',
                        'chicken_fresh','chicken_candidate_count',
                        'chicken_midlane_rejected','chicken_midlane_rejections',
                        'runtime_tick_gap_seconds','runtime_gap_recoveries',
                        'runtime_gap_recovery_active',
                        'tracking_starvation',
                        'tracking_starvation_seconds','sensor_desync',
                        'tracking_self_heals','sensor_desync_heals',
                        'tracking_rewarm','target_proposal_x',
                        'target_proposal_error_ratio','confirmed_jump_advances',
                        'slow_after_guard_active','recent_slow_pass_age',
                        'v5_safe_probability','v5_admission_threshold',
                        'v5_effective_difficulty','v5_physical_override',
                        'v5_observed_clear_override','v5_heuristic_probability',
                        'v5_longterm_probability','v5_session_probability',
                        'v5_session_train_n','v5_session_train_safe','v5_session_train_unsafe',
                        'v5_raw_decision',
                        'v5_commit_elapsed','v5_commit_required',
                        'v5_committed','v5_commit_age','v5_decision',
                        'v5_failure_similarity','v5_feedback_failures',
                        'v5_feedback_successes',
                        'green_signals','green_acted','green_active','rearm_needed',
                        'v5_gap_provenance','v5_verified_gap_fastpath',
                        'v5_verified_gap_action_lease','v5_verified_gap_min_action_lease',
                        'v5_verified_gap_physical_min_action_lease',
                        'v5_verified_gap_lease_tier',
                        'v5_verified_gap_selected_lease_required',
                        'v5_mode_physical_min_support',
                        'v5_mode_physical_min_confidence',
                        'v5_mode_physical_min_gap_p25',
                        'v5_required_eta',
                        'v5_historical_slow_after_risk','indicator_required_eta_override',
                        'green_outcome_successes','green_outcome_failures',
                        'visible_green_signal_id','pending_green_signal_id',
                        'green_viewport_rebases',
                        'analysis_anchor_x','analysis_anchor_y',
                        'chicken_anchor_stable','chicken_anchor_age','chicken_anchor_dx',
                        'lane_phase_error_ratio','lane_phase_shift_px',
                        'lane_phase_realigns','lane_phase_realigns_suppressed','lane_phase_bias_px',
                        'lane_phase_sync_reason','lane_phase_reanchored',
                        'perf_capture_ms','perf_chicken_ms','perf_lane_ms',
                        'perf_motion_ms','perf_risk_ms','perf_v5_ms',
                        'perf_preoutcome_ms','performance_recovery_mode',
                        'green_target_arrival_successes',
                        'green_progress_handoffs',
                        'green_rearm_geometry_releases',
                        'slow_window_profile_source','slow_window_follower_eta','slow_profile_recent_lane_support','slow_profile_recent_global_support','slow_profile_class_mismatches','slow_profile_directional_active','model_checkpoint_ok','model_checkpoint_ts','model_checkpoint_error',
                        'dynamic_gap_cycle_id','signal_admission_open','signal_admission_reason','green_missed_rearm_reason','green_missed_rearm_busy_cycle','green_missed_rearm_ready_cycle',
                        'runtime_tick_errors','runtime_tick_error_phase','runtime_tick_error_type',
                        'decision_frame_timestamp','green_display_deadline','green_display_expired',
                        'reset_candidate_pending','reset_confirmed_this_tick',
                        'upstream_arrival_eta','upstream_threat_id','upstream_required_seconds',
                        'upstream_prediction_available','upstream_prediction_blocked',
                        'v5_degraded_lease_headroom',
                        'v5_degraded_frame_margin',
                        'v5_sustained_observed_override',
                        'v5_active_green_hold_override',
                        'v5_post_pass_settle_required',
                        'v5_post_pass_clear_elapsed',
                        'v5_post_pass_ready',
                        'crossing_motion_available','crossing_motion_clear','crossing_motion_ratio','crossing_motion_reason','dynamic_gap_unlatched_lower_bound','detector_max_blob_area'
                    ])
                w.writerows(self.state_rows)
            self.state_rows.clear()

        if not save_model:
            return

        self.wait_for_checkpoint()
        return self._write_model_snapshot(self._model_payload())

    def _model_payload(self):
        return {
                'cluster': self.cluster, 'cluster_ready': self.cluster_ready,
                'type_cluster': self.type_cluster, 'type_ready': self.type_ready,
                'scaler': self.scaler, 'clf': self.clf, 'clf_ready': self.clf_ready,
                'supervised_n': self.supervised_n, 'observation_n': self.observation_n,
                'pattern_event_n': self.pattern_event_n,
                'crash_count': self.crash_count, 'crash_sample_n': self.crash_sample_n,
                'crash_memory': list(self.crash_memory),
                'safe_memory': list(self.safe_memory),
                'event_speeds': list(self.event_speeds),
                'type_speed': {k:list(v) for k,v in self.type_speed.items()},
                'events': {k:list(v) for k,v in self.events.items()},
                'pattern_gaps': {k:list(v) for k,v in self.pattern_gaps.items()},
                'global_pattern_gaps': {k:list(v) for k,v in self.global_pattern_gaps.items()},
                'pattern_next': {k:dict(v) for k,v in self.pattern_next.items()},
                'global_pattern_next': {k:dict(v) for k,v in self.global_pattern_next.items()},
                'green_failure_n': self.green_failure_n,
                'green_pattern_failures': dict(self.green_pattern_failures),
                'green_source_failures': dict(self.green_source_failures),
                'green_source_successes': dict(self.green_source_successes),
                'green_source_failure_etas': {
                    k:list(v) for k,v in self.green_source_failure_etas.items()
                },
                'green_source_action_delays': {
                    k:list(v) for k,v in self.green_source_action_delays.items()
                },
                'green_source_late_action_delays': {
                    k:list(v) for k,v in self.green_source_late_action_delays.items()
                },
                'green_source_late_failures': dict(
                    self.green_source_late_failures
                ),
                'green_late_action_observations': dict(
                    self.green_late_action_observations
                ),
                'green_success_n': self.green_success_n,
                'green_speed_successes': dict(self.green_speed_successes),
                'green_speed_failures': dict(self.green_speed_failures),
                'speed_pattern_gaps': {k:list(v) for k,v in self.speed_pattern_gaps.items()},
                'global_speed_pattern_gaps': {k:list(v) for k,v in self.global_speed_pattern_gaps.items()},
                'speed_pattern_next': {k:dict(v) for k,v in self.speed_pattern_next.items()},
                'global_speed_pattern_next': {k:dict(v) for k,v in self.global_speed_pattern_next.items()},
                'safe_label_n': self.safe_label_n,
                'unsafe_label_n': self.unsafe_label_n,
                'geometry_label_n': self.geometry_label_n,
                'green_attribution_policy_version': 550,
                'model_saved_at':time.time(),'slow_profile_policy':559,
            }

    def wait_for_checkpoint(self):
        worker=self._checkpoint_thread
        if worker is not None and worker.is_alive():
            worker.join()

    def request_checkpoint(self):
        """Freeze a coherent snapshot; serialize/write outside the GUI thread."""
        if self._checkpoint_thread is not None and self._checkpoint_thread.is_alive():
            return False
        try:
            payload=copy.deepcopy(self._model_payload())
        except Exception as exc:
            self.last_model_save_ok=False
            self.last_model_save_error=f'{type(exc).__name__}: {exc}'
            return False
        self._checkpoint_thread=threading.Thread(
            target=self._write_model_snapshot,args=(payload,),daemon=True)
        self._checkpoint_thread.start()
        return True

    def _write_model_snapshot(self,payload):
        try:
            tmp_path=str(self.state_path)+'.tmp'
            joblib.dump(payload,tmp_path)
            os.replace(tmp_path, self.state_path)
            self.last_model_save_ok=True
            self.last_model_save_ts=time.time()
            self.last_model_save_error=''
            return True
        except Exception as exc:
            self.last_model_save_ok=False
            self.last_model_save_error=f'{type(exc).__name__}: {exc}'
            return False

