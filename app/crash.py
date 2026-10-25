import time
from collections import deque


class CrashDetector:
    """V3.7 robust run-reset detector.

    Key change: a crash/reset no longer depends on a >=0.4 s disappearance.
    Once meaningful forward progress exists, a large confirmed regression back
    toward the run start becomes a reset candidate whether or not the chicken
    briefly disappeared between frames.

    A candidate must persist for multiple confirmed observations before it is
    emitted as a crash. Single-frame position glitches are therefore ignored.
    """

    def __init__(self, cfg):
        self.reset_back_px = float(cfg.get('reset_back_px', 180))
        self.min_progress_px = float(cfg.get('min_progress_px', 140))
        self.reset_near_start_px = float(cfg.get('reset_near_start_px', 120))
        self.confirm_frames = int(cfg.get('confirm_frames', 2))
        self.reset_cluster_radius = float(cfg.get('reset_cluster_radius_px', 90))
        self.dedup_seconds = float(cfg.get('dedup_seconds', 2.0))
        self.min_run_seconds = float(cfg.get('min_run_seconds', 1.0))
        self.initial_calibration_seconds = float(cfg.get('initial_calibration_seconds', 2.0))
        self.completion_suppression = bool(cfg.get('completion_suppression_enabled', False))
        self.max_forward_step_px = float(cfg.get('max_forward_step_px', 420.0))
        self.max_forward_step_frame_fraction = float(
            cfg.get('max_forward_step_frame_fraction', .38)
        )

        self.run_start_x = None
        self.run_started_at = None
        self.max_x = None
        self.last_confirmed_x = None
        self.last_seen_ts = None

        self.pending = None
        self.last_crash = -1e9
        self.crash_count = 0
        self.forward_spikes_ignored = 0
        self.recent_x = deque(maxlen=12)

    def _progress(self):
        if self.run_start_x is None or self.max_x is None:
            return 0.0
        return float(self.max_x - self.run_start_x)

    def _eligible(self, now):
        return (
            self.run_start_x is not None
            and self.max_x is not None
            and self._progress() >= self.min_progress_px
            and self.run_started_at is not None
            and now - self.run_started_at >= self.min_run_seconds
        )

    def _start_candidate(self, now, x, reason):
        self.pending = {
            'first_ts': float(now),
            'reason': reason,
            'count': 1,
            'sum_x': float(x),
            'start_x': float(self.run_start_x),
            'max_x': float(self.max_x),
        }

    def _advance_candidate(self, now, x):
        c = self.pending
        if c is None:
            return None

        mean_x = c['sum_x'] / max(1, c['count'])
        if abs(float(x) - mean_x) > self.reset_cluster_radius:
            self.pending = None
            return None

        if float(x) > c['start_x'] + self.reset_near_start_px:
            self.pending = None
            return None

        c['count'] += 1
        c['sum_x'] += float(x)

        if c['count'] < self.confirm_frames:
            return None

        reset_x = c['sum_x'] / c['count']
        event_time = c['first_ts']

        if event_time - self.last_crash < self.dedup_seconds:
            self.pending = None
            return None

        if (c['max_x'] - c['start_x']) < self.min_progress_px:
            self.pending = None
            return None

        self.last_crash = event_time
        self.crash_count += 1

        evt = {
            'crash': True,
            'event_time': float(event_time),
            'reason': c['reason'],
            'count': self.crash_count,
            'max_x': float(c['max_x']),
            'start_x': float(c['start_x']),
            'reset_x': float(reset_x),
            'progress_px': float(c['max_x'] - c['start_x']),
        }

        # New run begins from the stable reset position.
        self.run_start_x = float(reset_x)
        self.max_x = float(reset_x)
        self.run_started_at = float(now)
        self.last_confirmed_x = float(reset_x)
        self.pending = None
        self.recent_x.clear()
        self.recent_x.append(float(reset_x))
        return evt

    def suppress_last_crash_as_progress_reframe(self, chicken=None, now=None):
        """Undo crash bookkeeping after main proves this was game progress.

        The caller immediately applies the fullscreen reframe and rebases this
        detector once, so do not perform a second rebase here.
        """
        self.crash_count=max(0,int(self.crash_count)-1)
        self.last_crash=-1e9
        self.pending=None
        return self.crash_count

    def rebase_viewport(self, chicken=None, now=None):
        """Start a fresh screen-coordinate baseline after camera/view panning."""
        now=float(now if now is not None else time.time())
        self.pending=None
        self.recent_x.clear()
        if chicken is None:
            self.run_start_x=None
            self.max_x=None
            self.last_confirmed_x=None
            self.run_started_at=now
            return
        x=float(chicken.get('cx',0.0))
        self.run_start_x=x
        self.max_x=x
        self.last_confirmed_x=x
        self.run_started_at=now
        self.last_seen_ts=now
        self.recent_x.append(x)

    def update(self, chicken, frame_width=None, now=None):
        now = float(now if now is not None else time.time())

        # Pending/held CV positions do not move run state, but we deliberately
        # KEEP the last real position so a short disappearance cannot hide a reset.
        if chicken is None or not bool(chicken.get('detected', True)):
            return None

        x = float(chicken['cx'])
        self.last_seen_ts = now

        # A real one-lane move is a few hundred pixels even at 2x capture.
        # The latest V4.4.6 logs contained repeated 190 -> 2407 -> 190 colour
        # detector teleports.  Those single forward spikes set max_x and then
        # the return to the real chicken was falsely emitted as a crash.
        if self.last_confirmed_x is not None and frame_width is not None:
            forward_dx = x - float(self.last_confirmed_x)
            plausible = max(
                self.max_forward_step_px,
                float(frame_width) * self.max_forward_step_frame_fraction
            )
            if forward_dx > plausible:
                self.forward_spikes_ignored += 1
                return None

        self.recent_x.append(x)

        if self.run_start_x is None:
            self.run_start_x = x
            self.max_x = x
            self.run_started_at = now
            self.last_confirmed_x = x
            return None

        # During initial calibration, a lower stable position is allowed to
        # replace a bad first detection. Once real progress exists, a return
        # toward the start is treated as a possible reset instead.
        if (
            now - float(self.run_started_at) <= self.initial_calibration_seconds
            and self._progress() < self.min_progress_px
            and x < self.run_start_x
        ):
            self.run_start_x = x
            self.max_x = max(float(self.max_x), x)
            self.last_confirmed_x = x
            return None

        if self.pending is not None:
            evt = self._advance_candidate(now, x)
            self.last_confirmed_x = x
            return evt

        self.max_x = max(float(self.max_x), x)

        if self._eligible(now):
            regression = float(self.max_x - x)
            near_start = x <= float(self.run_start_x) + self.reset_near_start_px
            if regression >= self.reset_back_px and near_start:
                self._start_candidate(now, x, 'confirmed_progress_reset')
                self.last_confirmed_x = x
                return None

        self.last_confirmed_x = x
        return None
