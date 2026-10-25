import sys
import ctypes
try:
    import winsound
except Exception:
    winsound = None
import json
import time
import math
import traceback
from collections import deque
from pathlib import Path
import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget
from app.capture import ScreenCapture
from app.motion import MotionEngine
from app.scene_motion import ScenePanDetector, ProgressScrollGate, FullscreenProgressReframeGate
from app.target_lane import StableNextLane
from app.learning import OnlineLearner
from app.lane import LaneMapper
from app.risk import RiskEngine
from app.chicken import ChickenDetector
from app.indicator import StableRiskIndicator, required_eta_override_for_state
from app.crash import CrashDetector
from app.outcome import GreenJumpOutcomeTracker
from app.safe_window import SafeWindowPredictor
from app.upstream import predict_arrival, apply_guard, unresolved_vehicle, apply_unresolved_guard
from app.display_lease import DisplayLease, expire_state
from app.checkpoint import idle_checkpoint_due
from app.input_audit import InputAudit
from app.crossing import crossing_occupancy, apply_crossing_guard, crossing_bounds

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / 'config.json').read_text())



def _hide_console_window():
    """Hide the Windows console so MSS does not capture it over the game."""
    if not CFG.get('ui', {}).get('hide_console_on_start', True):
        return
    if sys.platform != 'win32':
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def _exclude_window_from_capture(widget):
    """Best-effort Windows 10/11 capture exclusion for the floating compass."""
    if not CFG.get('ui', {}).get('exclude_overlay_from_capture', True):
        return
    if sys.platform != 'win32':
        return
    try:
        hwnd = int(widget.winId())
        # WDA_EXCLUDEFROMCAPTURE = 0x11
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
    except Exception:
        pass


class Compass(QWidget):
    def __init__(self, getter):
        super().__init__()
        self.getter = getter
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(CFG['ui']['width'], CFG['ui']['height'])
        self.move(30, 120)
        self.drag = None
        self.presentation_events = []
        self._painted_green_id = None

    def showEvent(self, event):
        super().showEvent(event)
        _exclude_window_from_capture(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, e):
        self.drag = None

    def paintEvent(self, _):
        s = expire_state(self.getter(), time.time())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        risk = float(s.get('display_risk', s.get('risk', 50)))
        action = str(s.get('indicator_state', 'CHECKING'))
        painted_id = s.get('visible_green_signal_id') if action == 'CLEAR' else None
        if painted_id != self._painted_green_id:
            self.presentation_events.append(dict(
                kind='green_painted' if painted_id is not None else 'green_paint_ended',
                timestamp=time.time(), signal_id=painted_id if painted_id is not None else self._painted_green_id,
                deadline=s.get('green_display_deadline')))
            self.presentation_events = self.presentation_events[-256:]
            self._painted_green_id = painted_id

        if action == 'CLEAR':
            p.setBrush(QBrush(QColor(12, 34, 20, 248)))
            p.setPen(QPen(QColor(70, 255, 120, 255), 5))
        else:
            p.setBrush(QBrush(QColor(18, 18, 22, 238)))
            p.setPen(QPen(QColor(90, 90, 100, 220), 2))
        p.drawRoundedRect(5, 5, self.width()-10, self.height()-10, 22, 22)
        c = QColor(230,75,75) if action == 'WAIT' else QColor(235,180,65) if action in ('CAUTION','UNSTABLE','CHECKING','ETA HOLD','JUMPING','VERIFY LAND','RECHECK') else QColor(80,205,125)
        cx, cy = 57, 55
        p.setPen(QPen(QColor(120,120,130,130), 1)); p.drawEllipse(cx-36,cy-36,72,72)
        p.setBrush(QBrush(c)); p.setPen(QPen(c, 3)); p.drawEllipse(cx-13,cy-13,26,26)
        p.setPen(QPen(QColor(255,255,255))); p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        p.drawText(cx-18,cy+4,f'{int(risk)}%')

        p.setPen(QPen(c))
        p.setFont(QFont('Segoe UI', 15 if action == 'CLEAR' else 12, QFont.Weight.Bold))
        label = 'CLEAR ✓' if action == 'CLEAR' else action
        p.drawText(105, 35, 155, 26, Qt.AlignmentFlag.AlignLeft, label)
        p.setFont(QFont('Segoe UI', 8)); p.setPen(QPen(QColor(220,220,230)))
        tti=s.get('tti'); ttxt='--' if tti is None else f'{tti:.2f}s'
        eta_src = str(s.get('eta_source','unknown')).upper()
        if eta_src == 'CLEAR-ZONE':
            eta_src = 'CZN'
        elif eta_src == 'SLOW-BEFORE':
            eta_src = 'S-B'
        elif eta_src == 'SLOW-AFTER':
            eta_src = 'S-A'
        elif eta_src == 'CONFIRMED-SLOW-AFTER':
            eta_src = 'CS-A'
        elif eta_src == 'DYNAMIC-GAP':
            eta_src = 'DG'
        elif eta_src == 'GAP-OPEN':
            eta_src = 'OLD'
        elif eta_src == 'MOTION-SLOW-AFTER':
            eta_src = 'OLD'
        p.drawText(105, 59, 170, 16, Qt.AlignmentFlag.AlignLeft,
                   f"RAW {int(s.get('raw_risk',s.get('risk',0)))}% ETA {ttxt} {eta_src[:3]}")
        reason = str(s.get('clear_block_reason',''))
        if reason:
            p.setFont(QFont('Segoe UI', 7))
            p.drawText(105, 75, 170, 13, Qt.AlignmentFlag.AlignLeft, reason[:28])

        p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        chick = 'CHICKEN OK' if s.get('chicken_ok') else 'CHICKEN ?'
        conf = int(100*float(s.get('chicken_conf',0)))
        p.drawText(14, 98, 240, 15, Qt.AlignmentFlag.AlignLeft, f'{chick} {conf}%   X {int(s.get("chicken_x",0))} Y {int(s.get("chicken_y",0))}')
        p.setFont(QFont('Segoe UI', 8))
        tr=s.get('target_lane_distance_ratio')
        trtxt='--' if tr is None else f'{float(tr):.2f}x'
        anchor_mark='A✓' if s.get('chicken_anchor_stable',0) else 'A…'
        p.drawText(14, 116, 260, 15, Qt.AlignmentFlag.AlignLeft,
                   f"LANE {s.get('lane','-')} TGT {trtxt} {anchor_mark} FPS {s.get('processing_fps',0):.1f} "
                   f"S{s.get('safe_labels',0)} B{s.get('unsafe_labels',0)} "
                   f"P{s.get('pattern_events',0)}")
        if 'v5_safe_probability' in s:
            p.drawText(14, 134, 260, 15, Qt.AlignmentFlag.AlignLeft,
                       f"V5 {int(100*s.get('v5_safe_probability',0))}/{int(100*s.get('v5_safe_threshold',0))} "
                       f"M {str(s.get('difficulty_mode','N'))[:1]} "
                       f"N{s.get('v5_train_samples',0)} "
                       f"U{s.get('uncertain_incoming_count',0)}")
        else:
            p.drawText(14, 134, 260, 15, Qt.AlignmentFlag.AlignLeft,
                       f"CONF {int(100*s.get('adaptive_confidence',0))}/{int(100*s.get('adaptive_required_confidence',0))} "
                       f"VER {s.get('evidence_stable_elapsed',0):.1f}/{s.get('evidence_stable_required',0):.1f} "
                       f"U{s.get('uncertain_incoming_count',0)}")
        p.setPen(QPen(QColor(175,175,190))); p.setFont(QFont('Segoe UI', 7))
        cal = (
            f"E{s.get('czn_confirmed_events',0)}/{s.get('czn_required_events',6)} "
            f"R{s.get('czn_unique_raw_tracks',0)}/{s.get('czn_required_unique_tracks',8)}"
        )
        cal_mark = (
            s.get('czn_calibration_mode','OK')
            if s.get('czn_calibrated', False)
            else 'WAIT'
        )
        if s.get('dynamic_gap_recent_support',0):
            lease=s.get('dynamic_gap_action_lease')
            lease_txt='--' if lease is None else f"{float(lease):.2f}"
            patt=(
                f"DG Q{s.get('dynamic_gap_quantile',0):.0f} "
                f"REQ {s.get('dynamic_gap_required_eta',0):.2f} "
                f"RT {s.get('dynamic_gap_reaction_budget',0):.2f} "
                f"L {lease_txt}/{s.get('dynamic_gap_lease_required',0):.2f}"
            )
        elif s.get('slow_window_profile_support',0):
            patt=(
                f"SW {str(s.get('slow_window_mode','-')).replace('slow-','').upper() or '-'} "
                f"S{s.get('slow_window_profile_support',0)} "
                f"F{int(100*s.get('slow_window_p_fast',1))}% "
                f"G{0.0 if s.get('slow_window_p25_gap') is None else s.get('slow_window_p25_gap'):.2f}"
            )
        else:
            patt=(f"CAL {cal_mark} E{s.get('czn_confirmed_events',0)} "
                  f"R{s.get('czn_unique_raw_tracks',0)} "
                  f"MOT {100*s.get('motion_corridor_ratio',1):.1f}%/"
                  f"{s.get('motion_clear_dwell',0):.1f}s")
        p.drawText(14, 153, 265, 13, Qt.AlignmentFlag.AlignLeft, patt)
        p.drawText(14, 169, 265, 13, Qt.AlignmentFlag.AlignLeft,
                   f"CR {s.get('crashes',0)} CS {s.get('crash_samples',0)} "
                   f"EV+{s.get('run_events',0)} MS+{s.get('manual_successes',0)} "
                   f"MF+{s.get('manual_failures',0)} LATE+{s.get('late_reaction_observations',0)}")


class App:
    def __init__(self):
        self.capture = ScreenCapture(CFG['capture'])
        self.motion = MotionEngine(CFG['tracking'])
        self.scene = ScenePanDetector(CFG['tracking'])
        self.progress_scroll = ProgressScrollGate(CFG['tracking'])
        self.fullscreen_reframe = FullscreenProgressReframeGate(CFG['tracking'])
        self.fullscreen_reframe_mode = bool(CFG['tracking'].get('fullscreen_progress_reframe_mode', True))
        self.chicken = ChickenDetector(CFG['chicken'])
        self.lanes = LaneMapper(CFG['lanes'])
        self.learner = OnlineLearner(ROOT/'data'/'sessions', CFG['learning'])
        self.risk = RiskEngine(CFG['risk'])
        self.indicator = StableRiskIndicator(CFG.get('indicator', {}))
        self.crash = CrashDetector(CFG.get('crash_learning', {}))
        self.precrash = deque(maxlen=max(120, int(CFG['capture']['fps_limit'] * 6)))

        # V3.6 validates GREEN using actual chicken action/outcome.
        self.outcome = GreenJumpOutcomeTracker(CFG.get('outcome_learning', {}))
        self.safe_window_v5 = SafeWindowPredictor(ROOT, CFG.get('safe_window_v5', {}))

        self.green_display_lease=DisplayLease()
        self.green_expiry_timer=QTimer()
        self.green_expiry_timer.setSingleShot(True)
        self.green_expiry_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.green_expiry_timer.timeout.connect(self._expire_green_display)
        self.last_crash_notice = ''
        self._last_indicator_state = None
        self._last_clear_beep = 0.0
        self.last_crash_notice_until = 0.0
        self.last_valid_diag = {}
        self.last_frame_wall = None
        self.frame_dt_ema = 0.0
        self.passive_jump = None
        self.passive_last_x = None
        self.passive_stable_since = None
        self.passive_pre_state = None
        self.manual_failures = 0
        self.late_reaction_observations = 0
        self.chicken_forward_spikes_rejected = 0
        self.chicken_forward_spike_last = False

        # Performance + retrospective opportunity learning.
        self.frame_dt_hist = deque(maxlen=40)
        self.lag_hold_until = 0.0
        self.last_observe_ts = 0.0
        self.safe_candidates = deque(maxlen=12)
        self.last_safe_candidate_ts = {}
        self.last_fresh_chicken = None
        self.last_fresh_chicken_ts = 0.0
        self.tracking_chicken_hold_seconds = float(
            CFG['chicken'].get('tracking_hold_seconds',2.0)
        )
        self.decision_chicken_hold_seconds = float(
            CFG['chicken'].get('decision_hold_seconds',.70)
        )

        # V4.3.6: keep the watched-lane motion crop spatially FIXED while the
        # chicken remains on the same lane. MOG2 assumes pixel coordinates are
        # stable; shifting the crop by 1-3 px each frame made the whole ROI look
        # like foreground and destroyed vehicle tracking.
        self.motion_roi_lane = None
        self.motion_roi_rect = None
        self.motion_roi_frame_shape = None
        self.motion_roi_generation = 0
        self.viewport_was_unstable = False
        self.motion_rewarm_until = 0.0
        self.viewport_rebase_count = 0
        self.viewport_cumulative_shift = 0.0
        self.chicken_fresh_streak = 0
        # V5.0.3 stale-scene watchdog. Detect a live-changing frame whose tracked
        # chicken/target geometry has stopped updating; recover without user drag.
        self._watch_prev_gray = None
        self._watch_last_geom = None
        self._watch_last_geom_change = time.perf_counter()
        self._watch_recoveries = 0
        # V5.0.4: recover from post-jump/long-hold dead states without a manual
        # viewport nudge.  Track how long the locked target stays at/behind the
        # chicken and how long chicken localization is not freshly observed.
        self._landing_hold_since = None
        self._landing_recoveries = 0
        self._landing_wait_since = None
        self._landing_wait_watchdog_recoveries = 0
        self._roi_fallback_holds = 0
        self._forced_chicken_reacquires = 0
        self._last_forced_reacquire = -1e9
        # V5.1 tracking-health authority.  The V5.0.x stale watchdog depended
        # on chicken/target coordinates being pixel-perfectly frozen; detector
        # jitter kept resetting it even while the watched ROI was blind.
        self._track_starve_since = None
        self._tracking_self_heals = 0
        self._sensor_desync_heals = 0
        self._last_tracking_heal = -1e9
        # V5.2: target authority is chicken-relative geometry, not absence of
        # traffic. Empty lanes are legitimate and must never cause self-heal
        # churn. Only a sustained mismatch between the locked target and the
        # current immediate geometric proposal can re-anchor the target.
        self._last_target_proposal = None
        self._target_mismatch_since = None
        self._target_geometry_heals = 0
        self._confirmed_jump_advances = 0

        # V4.4.0: the next-lane mapper used to flip 0<->1 around a divider.
        # Every flip rebuilt the motion background and killed live calibration.
        self.run_pattern_start = int(self.learner.pattern_event_n)
        self.manual_lane_successes = 0
        self.pending_lane_success = None
        self.last_manual_success_switch = -1
        self.manual_success_duplicate_skips = 0
        self.manual_success_context_only = 0

        self.target_lane_lock = StableNextLane(
            arrival_fraction=float(
                CFG['tracking'].get('target_lane_arrival_fraction', .22)
            ),
            switch_min_seconds=float(
                CFG['tracking'].get('target_lane_switch_min_seconds', .35)
            ),
            min_ahead_fraction=float(
                CFG['tracking'].get('target_lane_min_ahead_fraction', .10)
            ),
            max_ahead_fraction=float(
                CFG['tracking'].get('target_lane_max_ahead_fraction', 1.55)
            ),
            reanchor_fraction=float(
                CFG['tracking'].get('target_lane_reanchor_fraction', .18)
            ),
            authoritative_min_fraction=float(
                CFG['tracking'].get('target_authoritative_min_fraction', .72)
            ),
            authoritative_max_fraction=float(
                CFG['tracking'].get('target_authoritative_max_fraction', 1.28)
            ),
            sync_improvement_fraction=float(
                CFG['tracking'].get('target_sync_improvement_fraction', .14)
            ),
        )

        # V5.3.3 chicken-authoritative geometry.  A stable, freshly detected
        # chicken is the spatial origin for the lane grid, target lane and ROI.
        # This is intentionally separate from GREEN thresholds: if geometry is
        # wrong, no amount of ML tuning can make the ETA calculation correct.
        self._anchor_probe_x = None
        self._anchor_probe_since = None
        self._anchor_stable = False
        self._anchor_age = 0.0
        self._anchor_last_dx = 0.0
        self._lane_phase_realigns = 0
        self._last_lane_phase_sync = -1e9
        self._last_lane_phase_shift = 0.0
        self._last_lane_phase_error_ratio = None
        self._lane_phase_sync_reason = 'INIT'
        # V5.3.6: do not re-phase a lane grid that already has the locked target
        # one lane ahead of the chicken. Repeated cosmetic phase corrections were
        # wiping live traffic history every few seconds and preventing gap proof.
        self._phase_realign_suppressed = 0

        self.last = {}
        self.input_audit=InputAudit(self.learner.folder/'input_audit_v5518.jsonl',lambda:self.last)
        self._tick_error_count=0
        self._last_tick_error_signature=None
        self._last_tick_error_log=-1e9
        self._tick_phase='initializing'
        self.last_save = time.time()
        self._last_idle_model_checkpoint=self.last_save
        self.last_debug_save = 0.0
        self._last_tick_wall = None
        self._last_tick_gap = 0.0
        self._runtime_gap_recoveries = 0
        self._runtime_gap_recovery_active = False
        self.ui = Compass(lambda: self.last); self.ui.show()
        self.crash_shortcut = QShortcut(QKeySequence('F8'), self.ui)
        self.crash_shortcut.activated.connect(self.manual_crash)
        self.timer = QTimer(); self.timer.timeout.connect(self._run_tick)
        self.timer.start(int(1000/CFG['capture']['fps_limit']))

    def _apply_viewport_rebase(self, dx, frame_width=None):
        """Move all screen-space state with a horizontal camera drag.

        The old implementation invalidated/reset several independent trackers.
        That created a dead period where chicken, target lane and traffic ROI
        referred to different coordinate frames.  Rebase them together first;
        safety attribution is still invalidated separately while the view moves.
        """
        dx=float(dx or 0.0)
        if abs(dx) < 1.0:
            return
        self.viewport_rebase_count += 1
        self.viewport_cumulative_shift += dx
        self.chicken.rebase_viewport(dx)
        self.lanes.rebase_viewport(dx)
        self.target_lane_lock.rebase_viewport(dx)
        self.motion.rebase_viewport(dx)
        self.outcome.rebase_viewport(dx)

        if self.last_fresh_chicken is not None:
            self.last_fresh_chicken['cx']=float(self.last_fresh_chicken.get('cx',0.0))+dx
            if 'x' in self.last_fresh_chicken:
                self.last_fresh_chicken['x']=float(self.last_fresh_chicken['x'])+dx
        if self.passive_last_x is not None:
            self.passive_last_x=float(self.passive_last_x)+dx
        if self.passive_jump is not None:
            for k in ('start_x','max_x','target_x'):
                if k in self.passive_jump:
                    self.passive_jump[k]=float(self.passive_jump[k])+dx
            # V5.2.9: the passive landing validator is now in the same rebased
            # coordinate frame. Mark that fact so a legitimate auto-scroll
            # during a successful jump does not permanently invalidate success.
            self.passive_jump['viewport_rebase_count']=int(self.viewport_rebase_count)

        if self.motion_roi_rect is not None:
            x1,y1,x2,y2=self.motion_roi_rect
            x1=float(x1)+dx; x2=float(x2)+dx
            if frame_width is not None:
                fw=float(frame_width)
                width=x2-x1
                if x1 < 0:
                    x2-=x1; x1=0.0
                if x2 > fw:
                    x1-=x2-fw; x2=fw
                x1=max(0.0,x1); x2=min(fw,max(x1+1.0,x2))
            self.motion_roi_rect=(int(round(x1)),int(y1),int(round(x2)),int(y2))

    def _apply_fullscreen_progress_reframe(self, dx, fresh_chicken, frame_width, wall_now, perf_now):
        """Rebase screen-space state for the game's deterministic 3-lane cut.

        Unlike a manual camera drag, the chicken detector has ALREADY observed
        the post-cut chicken coordinate on this frame. Therefore we translate
        the road/target/traffic/outcome state, but deliberately do not translate
        ChickenDetector's current reference a second time.
        """
        dx=float(dx or 0.0)
        if abs(dx) < 1.0:
            return
        self.viewport_rebase_count += 1
        self.viewport_cumulative_shift += dx
        self.lanes.rebase_viewport(dx)
        self.target_lane_lock.rebase_viewport(dx)
        self.motion.rebase_viewport(dx)
        self.outcome.rebase_viewport(dx)

        # Previous fresh position belongs to the pre-cut frame; translate it
        # into the new frame so the next identity comparison stays continuous.
        if self.last_fresh_chicken is not None:
            self.last_fresh_chicken['cx']=float(self.last_fresh_chicken.get('cx',0.0))+dx
            if 'x' in self.last_fresh_chicken:
                self.last_fresh_chicken['x']=float(self.last_fresh_chicken['x'])+dx
        if self.passive_last_x is not None:
            self.passive_last_x=float(self.passive_last_x)+dx
        if self.passive_jump is not None:
            for k in ('start_x','max_x','target_x'):
                if k in self.passive_jump:
                    self.passive_jump[k]=float(self.passive_jump[k])+dx
            self.passive_jump['viewport_rebase_count']=int(self.viewport_rebase_count)

        if self.motion_roi_rect is not None:
            x1,y1,x2,y2=self.motion_roi_rect
            x1=float(x1)+dx; x2=float(x2)+dx
            fw=float(frame_width or 0.0)
            if fw > 1.0:
                if x1 < 0:
                    x2-=x1; x1=0.0
                if x2 > fw:
                    x1-=x2-fw; x2=fw
                x1=max(0.0,x1); x2=min(fw,max(x1+1.0,x2))
            self.motion_roi_rect=(int(round(x1)),int(y1),int(round(x2)),int(y2))

        # This is game progress, NOT a death. Start CrashDetector from the new
        # first-lane coordinate before it can label the normal cut as a reset.
        self.crash.rebase_viewport(fresh_chicken,wall_now)
        # Preserve an ACTED GREEN across the cut (its coordinates were rebased),
        # but cancel any unacted permission from the old visual scene.
        self.outcome.invalidate_unacted_viewport(fresh_chicken,wall_now)
        self.safe_candidates.clear()
        self.passive_stable_since=None

        # The landed chicken becomes the new geometry origin after a short
        # settle. Do not inherit a pre-cut anchor dwell.
        self._anchor_probe_x=(None if fresh_chicken is None else float(fresh_chicken.get('cx',0.0)))
        self._anchor_probe_since=float(perf_now)
        self._anchor_stable=False
        self._anchor_age=0.0
        self._anchor_last_dx=0.0
        self.motion_rewarm_until=max(
            self.motion_rewarm_until,
            float(perf_now)+float(CFG['tracking'].get('fullscreen_reframe_rewarm_seconds',.10))
        )
        try:
            self.risk.notify_geometry_reanchor()
        except AttributeError:
            pass

    def _progress_scroll_state_from_reframe(self, perf_now, detected=False):
        st=self.fullscreen_reframe.status(perf_now)
        age=float(st.get('age',0.0))
        context_seconds=float(CFG['tracking'].get('progress_scroll_context_seconds',.90))
        in_context=bool(st.get('count',0) and age <= context_seconds)
        active=bool(st.get('active',False))
        return {
            'progress_scroll_active': bool(detected),
            'progress_scroll_settling': active,
            'progress_scroll_context': bool(active or in_context),
            'progress_scroll_age': age if (active or in_context) else 0.0,
            'progress_scroll_count': int(st.get('count',0)),
            'effective_stable': not active,
        }

    def _reset_target_lane(self):
        self.target_lane_lock.reset()

    def _update_chicken_anchor_stability(self, fresh_chicken, perf_now, scene_stable):
        """Track when the freshly detected chicken is horizontally landed/stable.

        Lane phase must never chase the sprite while it is actually jumping.
        We therefore make the chicken authoritative only after its X coordinate
        has stayed within a small lane-relative band for a short dwell.
        """
        if not bool(CFG['tracking'].get('chicken_anchor_enabled', True)):
            self._anchor_stable=False
            self._anchor_age=0.0
            return False
        if fresh_chicken is None or not bool(scene_stable):
            self._anchor_probe_x=None
            self._anchor_probe_since=None
            self._anchor_stable=False
            self._anchor_age=0.0
            self._anchor_last_dx=0.0
            return False

        cx=float(fresh_chicken.get('cx',0.0))
        sp=max(40.0,float(self.lanes.spacing or 185.0))
        tol=max(8.0,sp*float(CFG['tracking'].get('chicken_anchor_stable_fraction',.09)))
        now=float(perf_now)
        if self._anchor_probe_x is None or self._anchor_probe_since is None:
            self._anchor_probe_x=cx
            self._anchor_probe_since=now
            self._anchor_stable=False
            self._anchor_age=0.0
            self._anchor_last_dx=0.0
            return False

        dx=abs(cx-float(self._anchor_probe_x))
        self._anchor_last_dx=float(dx)
        if dx > tol:
            # Real lane-to-lane action (or a large identity correction): start a
            # new landing dwell. Do not move the road grid during this interval.
            self._anchor_probe_x=cx
            self._anchor_probe_since=now
            self._anchor_stable=False
            self._anchor_age=0.0
            return False

        # Follow only detector jitter, not lane motion.
        self._anchor_probe_x=.82*float(self._anchor_probe_x)+.18*cx
        self._anchor_age=max(0.0,now-float(self._anchor_probe_since))
        self._anchor_stable=bool(
            self._anchor_age >= float(CFG['tracking'].get('chicken_anchor_stable_seconds',.24))
        )
        return bool(self._anchor_stable)

    def _sync_lane_phase_to_chicken(self, fresh_chicken, perf_now, wall_now, scene_stable):
        """Make stable chicken position the authoritative screen-X geometry.

        If the periodic road detector is half a lane out of phase, re-phase the
        lane grid, immediately select the lane one spacing ahead of the chicken,
        and rebuild only the short-lived motion corridor state. Long-term model
        knowledge is deliberately preserved.
        """
        stable=self._update_chicken_anchor_stability(
            fresh_chicken,perf_now,scene_stable
        )
        self._last_lane_phase_shift=0.0
        self._lane_phase_sync_reason='ANCHOR_MOVING' if not stable else 'ALIGNED'
        if fresh_chicken is None or not self.lanes.ready or self.lanes.spacing is None:
            self._last_lane_phase_error_ratio=None
            self._lane_phase_sync_reason='NO_ANCHOR_OR_GRID'
            return False

        cx=float(fresh_chicken.get('cx',0.0))
        sp=max(40.0,float(self.lanes.spacing or 185.0))
        err=self.lanes.chicken_phase_error(cx)
        self._last_lane_phase_error_ratio=(None if err is None else float(err)/sp)
        if not stable:
            return False

        # V5.3.6: the target/chicken relationship is the geometry that matters
        # for ETA and the motion ROI. In the failed 68-minute run every phase
        # realignment happened while the locked target was already 0.98-1.06
        # lane ahead. Those needless corrections reset the motion-gap history,
        # so support could never reach the dynamic-gap minimum. If the target is
        # already in the authoritative next-lane band, keep the current corridor
        # and let minor road-grid phase jitter be diagnostic only.
        _locked_x=getattr(self.target_lane_lock,'lane_x',None)
        if _locked_x is not None:
            _locked_ratio=(float(_locked_x)-cx)/sp
            _amin=float(CFG['tracking'].get('target_authoritative_min_fraction',.72))
            _amax=float(CFG['tracking'].get('target_authoritative_max_fraction',1.28))
            if _amin <= _locked_ratio <= _amax:
                self._lane_phase_sync_reason='TARGET_ALREADY_ALIGNED'
                self._phase_realign_suppressed += 1
                return False

        if float(perf_now)-float(self._last_lane_phase_sync) < float(
            CFG['tracking'].get('lane_phase_realign_cooldown_seconds',.45)
        ):
            self._lane_phase_sync_reason='COOLDOWN'
            return False

        diag=self.lanes.align_phase_to_chicken(
            cx,
            min_fraction=float(CFG['tracking'].get('lane_phase_realign_min_fraction',.14)),
            max_fraction=float(CFG['tracking'].get('lane_phase_realign_max_fraction',.58)),
        )
        self._lane_phase_sync_reason=str(diag.get('reason',''))
        if not bool(diag.get('changed',False)):
            return False

        shift=float(diag.get('shift',0.0) or 0.0)
        self._last_lane_phase_shift=shift
        self._last_lane_phase_sync=float(perf_now)
        self._lane_phase_realigns += 1

        # The chicken is landed, so after phase correction the immediate lane is
        # exactly the first centre ahead. Make that target authoritative now.
        proposed=self.lanes.next_lanes(cx,count=1)
        if proposed:
            self.target_lane_lock.force_reanchor(
                proposed,float(wall_now),reason='CHICKEN_ANCHOR_SYNC'
            )
            self._last_target_proposal=(int(proposed[0][0]),float(proposed[0][1]))

        # The old motion background and clear-dwell evidence described a
        # different X corridor. Rebuild them, but keep learned vehicle/crash data.
        self.motion_roi_lane=None
        self.motion_roi_rect=None
        self.motion_roi_frame_shape=None
        self.motion_roi_generation += 1
        self.motion_rewarm_until=max(
            self.motion_rewarm_until,
            float(perf_now)+float(CFG['tracking'].get('lane_phase_rewarm_seconds',.12))
        )
        try:
            self.risk.notify_geometry_reanchor()
        except AttributeError:
            pass
        self.safe_candidates.clear()
        return True

    def _stable_next_lane(self, chicken, now):
        if chicken is None or not self.lanes.ready:
            self._last_target_proposal = None
            return None
        proposed=self.lanes.next_lanes(float(chicken['cx']),count=1)
        # V5.3.0: when both the locked target and normal nearest-ahead proposal
        # are already very close to the chicken, do not wait for a screen nudge.
        # The nearest-ahead selector is then pointing at the lane just consumed.
        # Independently choose a road-grid center roughly one spacing ahead.
        try:
            _sp=max(40.0,float(self.lanes.spacing or 185.0))
            _cx=float(chicken['cx'])
            _locked_ratio=(
                None if self.target_lane_lock.lane_x is None
                else (float(self.target_lane_lock.lane_x)-_cx)/_sp
            )
            _prop_ratio=(
                None if not proposed
                else (float(proposed[0][1])-_cx)/_sp
            )
            _consume_trigger=float(CFG['tracking'].get('consumed_target_trigger_fraction',.45))
            if (
                self._anchor_stable
                and _locked_ratio is not None and _locked_ratio <= _consume_trigger
                and (_prop_ratio is None or _prop_ratio <= _consume_trigger)
            ):
                _recovery=self.target_lane_lock.forward_recovery_candidate(
                    self.lanes.centers, _cx, _sp,
                    min_ratio=float(CFG['tracking'].get('consumed_target_next_min_fraction',.76)),
                    max_ratio=float(CFG['tracking'].get('consumed_target_next_max_fraction',1.38)),
                    min_advance_fraction=float(CFG['tracking'].get('consumed_target_min_advance_fraction',.45)),
                )
                if _recovery is not None:
                    proposed=[_recovery]
        except Exception:
            pass
        self._last_target_proposal = (None if not proposed else (int(proposed[0][0]),float(proposed[0][1])))
        # Once a lane-sized chicken move has survived the V5.2 multi-frame
        # identity confirmer it is a real positional transition. Advance the
        # target immediately to the new chicken-relative next lane instead of
        # leaving the ROI behind until a later viewport movement.
        if (
            proposed and bool(chicken.get('confirmed_teleport',False))
            and self._anchor_stable
        ):
            self._confirmed_jump_advances += 1
            return self.target_lane_lock.force_reanchor(proposed,float(now),reason='CONFIRMED_JUMP')
        if (
            bool(chicken.get('confirmed_teleport',False))
            and not self._anchor_stable
            and self.target_lane_lock.lane_id is not None
            and self.target_lane_lock.lane_x is not None
        ):
            # A large chicken transition was confirmed, but it has not yet
            # settled on its landing centre. Keep the lane being crossed until
            # the stable chicken anchor can select the next lane authoritatively.
            self.target_lane_lock.last_reason='WAIT_CHICKEN_LAND'
            return (int(self.target_lane_lock.lane_id),float(self.target_lane_lock.lane_x))
        result=self.target_lane_lock.update(
            proposed=proposed,
            chicken_x=float(chicken['cx']),
            spacing=float(self.lanes.spacing or 185.0),
            now=float(now),
        )
        return result


    def _save_debug(self, frame, tracks, chicken, state):
        dc = CFG.get('debug', {})
        if not dc.get('save_snapshot', True): return
        now=time.time(); interval=float(dc.get('snapshot_every_seconds',2.0))
        if now-self.last_debug_save<interval: return
        self.last_debug_save=now
        out=frame.copy()
        if chicken is not None:
            x1=int(chicken['cx']-chicken['w']/2); y1=int(chicken['cy']-chicken['h']/2)
            x2=int(chicken['cx']+chicken['w']/2); y2=int(chicken['cy']+chicken['h']/2)
            cv2.rectangle(out,(x1,y1),(x2,y2),(255,255,255),2)
            cv2.putText(out,'CHICKEN',(x1,max(20,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),2)
        lane_ids=[]
        if state.get('lane') not in (None,'-'): lane_ids.append(int(state['lane']))
        if state.get('lane2_id') is not None: lane_ids.append(int(state['lane2_id']))
        for i,lx in enumerate(self.lanes.centers):
            thick=3 if i in lane_ids else 1
            cv2.line(out,(int(lx),0),(int(lx),out.shape[0]),(255,255,255),thick)
            cv2.putText(out,f'L{i}',(int(lx)+4,35),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
        for t in tracks:
            x1=int(t['cx']-t['w']/2); y1=int(t['cy']-t['h']/2)
            x2=int(t['cx']+t['w']/2); y2=int(t['cy']+t['h']/2)
            cv2.rectangle(out,(x1,y1),(x2,y2),(180,180,180),1)
            cv2.putText(out,f"#{t['id']} {self.learner.speed_class(t['speed'])}",(x1,max(12,y1-3)),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
        d=ROOT/'data'/'debug'; d.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(d/'latest.jpg'),out)



    def _handle_green_outcome(self, event):
        if not event or event.get('kind') != 'green_outcome':
            return 0
        with (self.learner.folder/'outcome_audit_v555.jsonl').open('a',encoding='utf-8') as audit:
            audit.write(json.dumps({k:event.get(k) for k in (
                'signal_id','outcome','outcome_ts','start_ts','end_ts','action_start_ts',
                'landing_source','outcome_state','unknown_reason','crash_reason',
                'input_owned','input_movement_seen','input_validated_deadline','recorded_input_ts','attribution','weak_action_attribution'
            )})+'\n')
        if event.get('outcome') not in ('success', 'failure'):
            return 0
        self.risk.notify_green_outcome(event)
        # V5.2.2: the exact SafeWindow decision state must learn from the
        # action outcome too. V5.2.1 only trained OnlineLearner here, and late
        # GREEN failures were often skipped entirely, leaving V5 probability
        # at 95-98% after repeated crashes.
        v5_used = self.safe_window_v5.record_green_feedback(event)
        used = self.learner.record_green_outcome(event)
        if used or v5_used:
            if event.get('outcome') == 'failure':
                self.last_crash_notice = (
                    f"GREEN->CRASH #{event.get('signal_id','?')} "
                    f"LEARNED V5:{int(bool(v5_used))} SRC:{int(bool(used))}"
                )
            else:
                self.last_crash_notice = (
                    f"GREEN SUCCESS #{event.get('signal_id','?')} "
                    f"LEARNED V5:{int(bool(v5_used))} SRC:{int(bool(used))}"
                )
            self.last_crash_notice_until = time.time() + 3.5
            self.learner.flush(save_model=False)
        return 1 if (used or v5_used) else 0

    def _learn_crash_event(self, event):
        cfg = CFG.get('crash_learning', {})
        lookback = float(cfg.get('label_lookback_seconds', 2.0))
        skip = float(cfg.get('label_skip_recent_seconds', .10))
        et = float(event.get('event_time', time.time()))
        samples = [x for x in self.precrash if et-lookback <= x['timestamp'] <= et-skip]
        used = self.learner.learn_crash_window(samples, event)
        if used:
            self.last_crash_notice = f"CRASH LEARNED +{used}"
            self.last_crash_notice_until = time.time() + 4.0
        return used

    def manual_crash(self):
        now = time.time()
        evt = {
            'crash': True, 'event_time': now, 'reason': 'manual_F8',
            'count': self.crash.crash_count + 1
        }
        self.crash.crash_count += 1
        self.learner.reset_pattern_timing('manual_F8')
        self.risk.notify_crash(evt)

        green_failure = self.outcome.on_crash(evt, now)
        if green_failure is not None:
            self._handle_green_outcome(green_failure)

        self._learn_crash_event(evt)
        self.indicator.update(
            99.0, visible_threat=True, eta=None,
            eta_source='unknown', now=time.perf_counter()
        )


    def _expire_green_display(self):
        state=self.last
        deadline=state.get('green_display_deadline')
        if deadline is None or state.get('indicator_state')!='CLEAR':
            return
        now=time.time()
        if now < float(deadline):
            self.green_expiry_timer.start(max(1,math.ceil(1000*(float(deadline)-now))))
            return
        self.last=expire_state(state,now)
        self.outcome.expire_display(float(deadline))
        self.indicator.clear_hold_until=0.0
        self._last_indicator_state='ETA HOLD'
        self.ui.update()

    def _notify_indicator_transition(self, state, now):
        action = str(state.get('indicator_state', 'CHECKING'))
        if action == 'CLEAR' and self._last_indicator_state != 'CLEAR':
            try:
                self.learner.flush(save_model=False)
            except Exception:
                pass
            try:
                self.ui.raise_()
            except Exception:
                pass

            if (
                CFG.get('ui', {}).get('beep_on_clear', True)
                and winsound is not None
                and now - self._last_clear_beep > .8
            ):
                try:
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    self._last_clear_beep = now
                except Exception:
                    pass

        self._last_indicator_state = action

    def _run_tick(self):
        """Keep Qt slot failures visible and revoke stale screen permission."""
        try:
            self.tick()
        except Exception as exc:
            self._tick_error_count += 1
            now=time.time()
            self.green_expiry_timer.stop()
            self.outcome.expire_display(now)
            self.indicator.clear_hold_until=0.0
            self._last_indicator_state='TRACK ERROR'
            self.last={**self.last,
                'indicator_state':'TRACK ERROR','green_confirmed':False,
                'green_evidence_ok':False,'chicken_fresh':0,
                'chicken_position_confirmed':False,
                'green_evidence_reason':'UPDATE ERROR - SEE RUNTIME LOG',
                'clear_block_reason':'UPDATE ERROR - SEE RUNTIME LOG',
                'runtime_tick_errors':self._tick_error_count,
                'runtime_tick_error_phase':self._tick_phase,
                'runtime_tick_error_type':type(exc).__name__,
            }
            self.ui.update()
            signature=(self._tick_phase,type(exc).__name__,str(exc))
            if signature!=self._last_tick_error_signature or now-self._last_tick_error_log>=5.0:
                try:
                    with (self.learner.folder/'runtime_errors_v5518.log').open('a',encoding='utf-8') as log:
                        log.write(f"{now:.6f} phase={self._tick_phase} count={self._tick_error_count}\n")
                        log.write(traceback.format_exc()+'\n')
                except OSError:
                    pass
                self._last_tick_error_signature=signature
                self._last_tick_error_log=now

    def tick(self):
        self._tick_phase='capture'
        for record in self.input_audit.drain():
            self.outcome.observe_input(record,time.time())
        self._expire_green_display()
        tick_started=time.perf_counter()
        frame=self.capture.grab()
        capture_ms=1000.0*(time.perf_counter()-tick_started)
        if frame is None:
            return

        perf_now=time.perf_counter()
        wall_now=time.time()

        # V5.4.7 runtime-gap watchdog. Supplied telemetry contains 23.4 s and
        # later 13-15 s gaps while the game itself keeps running. On resume,
        # discard stale screen-space state and relock from the current frame.
        self._runtime_gap_recovery_active=False
        if self._last_tick_wall is not None:
            self._last_tick_gap=max(0.0,wall_now-float(self._last_tick_wall))
            if self._last_tick_gap >= float(
                CFG['tracking'].get('runtime_gap_recovery_seconds',1.50)
            ):
                self._runtime_gap_recoveries += 1
                self._runtime_gap_recovery_active=True
                self.chicken.force_reacquire()
                self.target_lane_lock.reset()
                self.motion.force_reset()
                self.motion_roi_lane=None
                self.motion_roi_rect=None
                self.motion_roi_frame_shape=None
                self.motion_roi_generation += 1
                self._anchor_probe_x=None
                self._anchor_probe_since=None
                self._anchor_stable=False
                self._anchor_age=0.0
                self.safe_candidates.clear()
                try:
                    self.risk.notify_geometry_reanchor()
                except AttributeError:
                    pass
        else:
            self._last_tick_gap=0.0
        self._last_tick_wall=wall_now

        # Lightweight full-frame freshness metric, independent of vehicle tracker.
        _wg=cv2.cvtColor(cv2.resize(frame,(160,90),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2GRAY)
        if self._watch_prev_gray is None:
            frame_activity=0.0
        else:
            frame_activity=float(np.mean(cv2.absdiff(_wg,self._watch_prev_gray)))
        self._watch_prev_gray=_wg
        scene=self.scene.update(frame,perf_now)
        # V5.3.5: fullscreen gameplay has one deterministic viewport event: after
        # the third visible lane, the game CUTS the completed lanes and places
        # the chicken back on the first visible lane. Generic scene correlation
        # was falsely treating moving traffic as camera motion (149 rebases in
        # the failing V5.3.4 run). In fullscreen mode raw pan remains telemetry
        # only; it has no authority to move the lane/chicken coordinate frame.
        if self.fullscreen_reframe_mode:
            progress_scroll=self._progress_scroll_state_from_reframe(perf_now)
            scene_stable=bool(progress_scroll.get('effective_stable',True))
            viewport_unstable=not scene_stable
        else:
            progress_scroll=self.progress_scroll.update(scene,perf_now)
            scene_stable=bool(progress_scroll.get('effective_stable',scene.get('stable',True)))
            viewport_unstable=not scene_stable

        # Manual/non-fullscreen mode still supports generic camera dragging.
        if bool(scene.get('pan_active',False)) and not self.fullscreen_reframe_mode:
            self._apply_viewport_rebase(
                float(scene.get('shift_px',0.0)), frame_width=frame.shape[1]
            )

        if self.last_frame_wall is not None:
            fdt=max(0.0,wall_now-self.last_frame_wall)
            self.frame_dt_hist.append(fdt)
            if fdt > float(CFG['risk'].get('hard_processing_stall_seconds', .55)):
                self.lag_hold_until = perf_now + float(
                    CFG['risk'].get('processing_recovery_seconds', .65)
                )
        self.last_frame_wall=wall_now

        if self.frame_dt_hist:
            median_dt=float(np.median(np.asarray(self.frame_dt_hist,dtype=float)))
        else:
            median_dt=1.0/max(1.0,float(CFG['capture']['fps_limit']))
        processing_fps=1.0/max(.001,median_dt)
        normal_processing_floor=float(
            CFG['risk'].get('min_processing_fps_for_green',2.8)
        )
        degraded_processing_floor=float(
            CFG['risk'].get('degraded_min_processing_fps_for_green',2.0)
        )
        processing_degraded=bool(
            len(self.frame_dt_hist)>=8
            and degraded_processing_floor <= processing_fps < normal_processing_floor
        )
        # V5.4.9: do not turn low-but-stable FPS into a global no-GREEN state.
        # SafeWindow already requires >= one full processed-frame of extra
        # action lease via frame_margin=(1/FPS)+0.04. Hard stalls still trigger
        # lag_hold_until and remain blocked.
        processing_healthy=bool(
            perf_now >= self.lag_hold_until
            and (
                len(self.frame_dt_hist)<8
                or processing_fps >= degraded_processing_floor
            )
        )

        # Chicken detection may flicker for a few frames. Keep the last fresh
        # geometry for TRAFFIC LEARNING only, but never allow GREEN while the
        # chicken is not freshly detected.
        try:
            self.chicken.set_lane_spacing(self.lanes.spacing if self.lanes.ready else None)
        except AttributeError:
            pass
        _perf_ch=time.perf_counter()
        self._tick_phase='chicken_detection'
        detected_chicken=self.chicken.detect(frame)
        chicken_detect_ms=1000.0*(time.perf_counter()-_perf_ch)
        fresh_chicken=(
            detected_chicken
            if detected_chicken is not None and bool(detected_chicken.get('detected',False))
            else None
        )

        self.outcome.confirm_input_movement(fresh_chicken)

        # V5.3.5: detect the game's real fullscreen 3-lane cut directly from
        # chicken geometry. A valid cut is ~two lane spacings backwards and
        # lands near the first visible lane. One-lane death resets are NOT
        # classified as progress reframes.
        _reframe_evt={'detected':False,'active':False,'count':0,'dx':0.0,'shift_lanes':0.0,'age':0.0}
        if self.fullscreen_reframe_mode:
            _sp=self.lanes.spacing
            if _sp is None:
                _refw=float(CFG['lanes'].get('reference_width_px',1280.0))
                _base=float(CFG['lanes'].get('divider_expected_spacing_px',221.0))
                _sp=_base*(float(frame.shape[1])/max(1.0,_refw))
            _reframe_evt=self.fullscreen_reframe.update(
                fresh_chicken,_sp,frame.shape[1],perf_now
            )
            if bool(_reframe_evt.get('detected',False)):
                self._apply_fullscreen_progress_reframe(
                    float(_reframe_evt.get('dx',0.0)),fresh_chicken,
                    frame.shape[1],wall_now,perf_now
                )
                progress_scroll=self._progress_scroll_state_from_reframe(
                    perf_now,detected=True
                )
                scene_stable=False
                viewport_unstable=True
            else:
                _rs=self.fullscreen_reframe.status(perf_now)
                if bool(_rs.get('active',False)):
                    progress_scroll=self._progress_scroll_state_from_reframe(perf_now)
                    scene_stable=False
                    viewport_unstable=True

        # V4.4.7: reject impossible FORWARD chicken teleports before they can
        # poison crash/manual learning.  Latest logs repeatedly jumped from
        # x~190 to a static right-edge colour match around x~2384-2474, then
        # returned to the real chicken and produced a fake progress-reset crash.
        # Negative jumps are intentionally not filtered here because a genuine
        # death/reset must remain visible to CrashDetector.
        self.chicken_forward_spike_last=False
        if (
            fresh_chicken is not None
            and self.last_fresh_chicken is not None
            and self.lanes.ready
            and not viewport_unstable
        ):
            spacing=max(120.0,float(self.lanes.spacing or 185.0))
            forward_dx=(
                float(fresh_chicken.get('cx',0.0))
                - float(self.last_fresh_chicken.get('cx',0.0))
            )
            max_forward=max(420.0,2.20*spacing)
            if forward_dx > max_forward:
                self.chicken_forward_spikes_rejected += 1
                self.chicken_forward_spike_last=True
                self.chicken.restore_reference(self.last_fresh_chicken)
                held=dict(self.last_fresh_chicken)
                held['detected']=False
                held['pending_position']=True
                held['forward_spike_rejected']=True
                detected_chicken=held
                fresh_chicken=None

        if fresh_chicken is not None:
            self.last_fresh_chicken=dict(fresh_chicken)
            self.last_fresh_chicken_ts=wall_now
            self.chicken_fresh_streak = (
                self.chicken_fresh_streak + 1 if not viewport_unstable else 0
            )
        else:
            self.chicken_fresh_streak = 0

        chicken=detected_chicken
        if (
            chicken is None
            and self.last_fresh_chicken is not None
            and wall_now-self.last_fresh_chicken_ts <= self.tracking_chicken_hold_seconds
        ):
            chicken=dict(self.last_fresh_chicken)
            chicken['detected']=False
            chicken['tracking_only']=True
            chicken['confidence']=min(.20,float(chicken.get('confidence',.20)))

        chicken_fresh = fresh_chicken is not None
        chicken_age = (1e9 if self.last_fresh_chicken is None
                       else max(0.0,wall_now-self.last_fresh_chicken_ts))
        chicken_trusted = bool(
            chicken is not None and (
                chicken_fresh or (
                    chicken_age <= self.decision_chicken_hold_seconds
                    and not bool(chicken.get('pending_position',False))
                )
            )
        )
        # V5.2.4 performance recovery: once the divider grid is locked, do not
        # spend a full-frame HSV lane scan while processing FPS is already low.
        # Scene-pan rebasing keeps the locked grid aligned; normal refresh resumes
        # automatically after FPS recovers.
        lane_scan_frame = frame
        if (self.lanes.ready and processing_fps < float(CFG['risk'].get('performance_lane_scan_disable_fps',4.0))):
            lane_scan_frame = None
        _perf_lane=time.perf_counter()
        self.lanes.update([],lane_scan_frame)
        lane_scan_ms=1000.0*(time.perf_counter()-_perf_lane)

        # V5.3.3: before choosing any traffic ROI, reconcile the periodic road
        # grid with a freshly detected, horizontally stable chicken. Every
        # downstream target/ETA/motion calculation then shares this same origin.
        self._tick_phase='target_geometry'
        lane_phase_reanchored=self._sync_lane_phase_to_chicken(
            fresh_chicken,perf_now,wall_now,scene_stable
        )

        # V4.3.8: single-lane ROI, spatially stable while the viewport is
        # stable, but RE-ANCHORED after a horizontal game-screen pan.
        # This frame may have no chicken or lane grid. Never reuse an old
        # target or leave the risk-engine override uninitialized on that path.
        nxt=[]
        tracking_roi=None
        tracking_roi_key=None
        tracking_roi_area_pct=100.0
        tracking_roi_lanes=[]
        roi_reanchored=False

        if chicken is not None and self.lanes.ready:
            stable_target = self._stable_next_lane(chicken, wall_now)
            nxt = [] if stable_target is None else [stable_target]
            if nxt:
                li,lx=nxt[0]
                li=int(li)
                tracking_roi_lanes=[li]

                h,w=frame.shape[:2]
                frame_shape_key=(h,w)
                spacing=float(self.lanes.spacing or 185.0)
                half=max(
                    float(CFG['tracking'].get('roi_min_half_width_px',110.0)),
                    spacing*float(CFG['tracking'].get('roi_spacing_half_factor',.62))
                )
                lane_x=float(lx)
                desired=(int(max(0,round(lane_x-half))),
                         int(max(0,round(h*float(CFG['tracking'].get('roi_top_ratio',.035))))),
                         int(min(w,round(lane_x+half))),
                         int(min(h,round(float(chicken['cy'])+
                             float(CFG['tracking'].get('roi_below_chicken_px',145))))))

                need_new=bool(
                    self.motion_roi_lane != li
                    or self.motion_roi_rect is None
                    or self.motion_roi_frame_shape != frame_shape_key
                )

                if not need_new and self.motion_roi_rect is not None:
                    old_center=(self.motion_roi_rect[0]+self.motion_roi_rect[2])/2.0
                    drift=abs(lane_x-old_center)
                    drift_limit=max(
                        float(CFG['tracking'].get('roi_reanchor_min_px',28.0)),
                        spacing*float(CFG['tracking'].get('roi_reanchor_spacing_fraction',.14))
                    )
                    # V5.5.12: a crop selected during the jump can end above
                    # the resting crossing strip. Recover missing coverage once;
                    # ordinary y jitter must not continually reset the detector.
                    bx1,by1,bx2,by2=crossing_bounds(lane_x,chicken,self.risk)
                    ox1,oy1,ox2,oy2=self.motion_roi_rect
                    missing_coverage=(by1<oy1 or by2>oy2)
                    if missing_coverage and scene_stable:
                        # Expand, never shrink on vertical movement. Retain the
                        # existing 145px below-chicken margin for settling/jitter.
                        desired=(desired[0],
                                 max(0,min(desired[1],oy1,by1)),
                                 desired[2],
                                 min(h,max(desired[3],oy2,by2)))
                        # Offscreen geometry remains unavailable; do not reset
                        # the background repeatedly when expansion is impossible.
                        if desired[1] != oy1 or desired[3] != oy2:
                            need_new=True
                    # During the drag, block decisions and wait. Once the road
                    # has stabilized, move the crop once and rebuild background.
                    if drift >= drift_limit and scene_stable:
                        need_new=True

                if need_new and scene_stable:
                    x1,y1,x2,y2=desired
                    if x2-x1>=90 and y2-y1>=120:
                        self.motion_roi_lane=li
                        self.motion_roi_rect=desired
                        self.motion_roi_frame_shape=frame_shape_key
                        self.motion_roi_generation += 1
                        roi_reanchored=True
                        _roi_rewarm_key=(
                            'progress_scroll_rewarm_seconds'
                            if bool(progress_scroll.get('progress_scroll_context',False))
                            else 'roi_rewarm_seconds'
                        )
                        self.motion_rewarm_until=perf_now+float(
                            CFG['tracking'].get(_roi_rewarm_key, CFG['tracking'].get('roi_rewarm_seconds',.55))
                        )

                tracking_roi=self.motion_roi_rect
                tracking_roi_key=(li,self.motion_roi_generation)
                if tracking_roi is not None:
                    x1,y1,x2,y2=tracking_roi
                    tracking_roi_area_pct=100.0*((x2-x1)*(y2-y1))/float(w*h)

        # V5.2.5 performance hold: if target geometry temporarily disappears,
        # keep processing the last bounded motion ROI instead of falling back to
        # a full-screen motion pass.  GREEN is still blocked by TARGET geometry,
        # so this preserves performance/history without authorizing stale lanes.
        roi_fallback_hold=False
        if tracking_roi is None and self.motion_roi_rect is not None:
            h,w=frame.shape[:2]
            if self.motion_roi_frame_shape == (h,w):
                tracking_roi=self.motion_roi_rect
                tracking_roi_key=(self.motion_roi_lane,self.motion_roi_generation)
                x1,y1,x2,y2=tracking_roi
                tracking_roi_area_pct=100.0*((x2-x1)*(y2-y1))/float(w*h)
                roi_fallback_hold=True
                self._roi_fallback_holds += 1


        # Viewport motion invalidates all screen-X action/crash attribution.
        if viewport_unstable and not self.viewport_was_unstable:
            self.outcome.invalidate_unacted_viewport(fresh_chicken,wall_now)
            self.passive_jump=None
            self.passive_stable_since=None
            self.passive_last_x=None
            self.safe_candidates.clear()

        if (not viewport_unstable) and self.viewport_was_unstable:
            # The viewport is stable again.  V5.0.2 has already translated
            # chicken/lane/ROI coordinates during the drag, so KEEP the target
            # lock instead of throwing it away. Rebase crash/outcome baselines
            # rather than interpreting the new screen X as game progress.
            self.crash.rebase_viewport(fresh_chicken,wall_now)
            # Preserve an acted GREEN across the camera settle. Its stored
            # screen coordinates were translated on every pan frame above.
            self.passive_last_x=(
                None if fresh_chicken is None
                else float(fresh_chicken.get('cx',0.0))
            )
            # Force a clean spatial background at the post-pan crop.
            if self.motion_roi_rect is not None:
                self.motion_roi_generation += 1
                tracking_roi_key=(self.motion_roi_lane,self.motion_roi_generation)
                self.motion.force_reset(roi_key=tracking_roi_key)
                _rewarm_key=(
                    'progress_scroll_rewarm_seconds'
                    if bool(progress_scroll.get('progress_scroll_context',False))
                    else 'roi_rewarm_seconds'
                )
                self.motion_rewarm_until=perf_now+float(
                    CFG['tracking'].get(_rewarm_key, CFG['tracking'].get('roi_rewarm_seconds',.55))
                )

        self.viewport_was_unstable=viewport_unstable

        _perf_motion=time.perf_counter()
        self._tick_phase='vehicle_tracking'
        tracks=self.motion.update(
            frame,perf_now,roi=tracking_roi,roi_key=tracking_roi_key
        )
        motion_ms=1000.0*(time.perf_counter()-_perf_motion)
        # Fallback traffic-based lane learning only matters before markings lock.
        if not self.lanes.ready:
            self.lanes.update(tracks,None)

        # Expensive unsupervised type/session observation is decimated. Crossing
        # events remain every frame because those are timing-critical.
        observe_interval=float(CFG['learning'].get('observe_interval_seconds',.25))
        if processing_healthy and wall_now-self.last_observe_ts >= observe_interval:
            self.learner.observe(tracks,self.lanes)
            self.last_observe_ts=wall_now
        self.learner.observe_pass_events(
            tracks, self.lanes, chicken,
            watched_lane=(tracking_roi_lanes[0] if tracking_roi_lanes else None)
        )

        _perf_risk=time.perf_counter()
        self._tick_phase='risk_evaluation'
        state=self.risk.evaluate(
            tracks,self.learner,self.lanes,frame.shape,chicken,
            frame=frame,motion_mask=self.motion.last_mask,
            lane_override=(nxt[0] if nxt else None),
            pipeline_latency_seconds=median_dt
        )
        risk_ms=1000.0*(time.perf_counter()-_perf_risk)
        state['processing_fps']=processing_fps
        state['processing_lag_ms']=1000.0*median_dt
        state['processing_healthy']=processing_healthy
        state['processing_degraded']=int(processing_degraded)
        state['processing_green_floor_fps']=float(degraded_processing_floor)
        state['tracking_roi_lane']=('-' if not tracking_roi_lanes else str(tracking_roi_lanes[0]))
        state['tracking_roi_lanes']=list(tracking_roi_lanes)
        state['chicken_fresh']=bool(chicken_fresh)
        state['chicken_trusted']=bool(chicken_trusted)
        state['chicken_fresh_age']=float(chicken_age)
        state['chicken_candidate_count']=int(
            getattr(self.chicken,'last_candidates',0)
        )
        state['chicken_midlane_rejected']=int(bool(
            getattr(self.chicken,'last_midlane_rejected',False)
        ))
        state['chicken_midlane_rejections']=int(
            getattr(self.chicken,'midlane_rejections',0)
        )
        state['runtime_tick_gap_seconds']=float(self._last_tick_gap)
        state['runtime_gap_recoveries']=int(self._runtime_gap_recoveries)
        state['runtime_gap_recovery_active']=int(
            bool(self._runtime_gap_recovery_active)
        )
        state['tracking_roi_area_pct']=tracking_roi_area_pct
        state['tracking_roi_fallback_hold']=int(roi_fallback_hold)
        state['tracking_roi_fallback_holds']=int(self._roi_fallback_holds)
        state['target_lane_locked']=(
            '-' if self.target_lane_lock.lane_id is None
            else str(self.target_lane_lock.lane_id)
        )
        state['target_lane_x']=(
            0.0 if self.target_lane_lock.lane_x is None
            else float(self.target_lane_lock.lane_x)
        )
        state['target_lane_switches']=int(
            self.target_lane_lock.switches
        )
        target_geom=self.target_lane_lock.geometry(
            float(chicken['cx']) if chicken is not None else 0.0,
            float(self.lanes.spacing or 185.0)
        )
        state['target_lane_geometry_ok']=bool(target_geom.get('ok',False))
        state['target_lane_distance']=(
            None if target_geom.get('distance') is None
            else float(target_geom.get('distance'))
        )
        state['target_lane_distance_ratio']=(
            None if target_geom.get('ratio') is None
            else float(target_geom.get('ratio'))
        )
        state['target_lane_lock_reason']=str(
            target_geom.get('reason','')
        )
        state['target_lane_relocks']=int(
            self.target_lane_lock.relocks
        )
        # V5.3.3 anchor diagnostics. The model is allowed to certify target
        # geometry only when the fresh chicken has actually settled; this stops
        # in-flight sprite coordinates from advancing the watched lane.
        state['analysis_anchor_x']=(
            0.0 if chicken is None else float(chicken.get('cx',0.0))
        )
        state['analysis_anchor_y']=(
            0.0 if chicken is None else float(chicken.get('cy',0.0))
        )
        state['chicken_anchor_stable']=int(bool(self._anchor_stable))
        state['chicken_anchor_age']=float(self._anchor_age)
        state['chicken_anchor_dx']=float(self._anchor_last_dx)
        state['lane_phase_error_ratio']=(
            None if self._last_lane_phase_error_ratio is None
            else float(self._last_lane_phase_error_ratio)
        )
        state['lane_phase_shift_px']=float(self._last_lane_phase_shift)
        state['lane_phase_realigns']=int(self._lane_phase_realigns)
        state['lane_phase_realigns_suppressed']=int(self._phase_realign_suppressed)
        state['lane_phase_bias_px']=float(getattr(self.lanes,'phase_bias',0.0))
        state['lane_phase_sync_reason']=str(self._lane_phase_sync_reason)
        state['lane_phase_reanchored']=int(bool(lane_phase_reanchored))
        tr=state.get('target_lane_distance_ratio')
        try:
            tr=float(tr)
            state['target_green_geometry_ok']=bool(
                self._anchor_stable
                and float(CFG['tracking'].get('target_green_min_ahead_fraction',.64))
                    <= tr
                    <= float(CFG['tracking'].get('target_green_max_ahead_fraction',1.30))
            )
        except Exception:
            state['target_green_geometry_ok']=False
        state['scene_pan_active']=bool(scene.get('pan_active',False))
        state['scene_pan_raw_stable']=bool(scene.get('stable',False))
        state['scene_pan_stable']=bool(scene_stable)
        state['game_progress_scroll_active']=int(bool(progress_scroll.get('progress_scroll_active',False)))
        state['game_progress_scroll_settling']=int(bool(progress_scroll.get('progress_scroll_settling',False)))
        state['game_progress_scroll_context']=int(bool(progress_scroll.get('progress_scroll_context',False)))
        state['game_progress_scroll_count']=int(progress_scroll.get('progress_scroll_count',0))
        state['game_progress_scroll_age']=float(progress_scroll.get('progress_scroll_age',0.0))
        _frs=self.fullscreen_reframe.status(perf_now)
        state['fullscreen_reframe_active']=int(bool(_frs.get('active',False)))
        state['fullscreen_reframe_count']=int(_frs.get('count',0))
        state['fullscreen_reframe_shift_px']=float(_frs.get('dx',0.0))
        state['fullscreen_reframe_shift_lanes']=float(_frs.get('shift_lanes',0.0))
        state['fullscreen_reframe_age']=float(_frs.get('age',0.0))
        state['raw_scene_pan_ignored']=int(bool(
            self.fullscreen_reframe_mode and scene.get('pan_active',False)
        ))
        state['scene_shift_px']=float(scene.get('shift_px',0.0))
        state['scene_pan_score']=float(scene.get('score',0.0))
        state['scene_pan_count']=int(scene.get('pan_count',0))
        state['viewport_rebase_count']=int(self.viewport_rebase_count)
        state['viewport_cumulative_shift']=float(self.viewport_cumulative_shift)
        state['chicken_fresh_streak']=int(self.chicken_fresh_streak)
        state['motion_mog_ratio']=float(self.motion.last_mog_ratio)
        state['motion_diff_ratio']=float(self.motion.last_diff_ratio)
        state['motion_ready']=bool(
            self.motion.last_mask is not None
            and self.motion.last_mask.get('ready',False)
            and perf_now >= self.motion_rewarm_until
        )
        state['lane_mapper_ready']=bool(self.lanes.ready)
        state['lane_mapper_source']=str(self.lanes.source)
        state['lane_mapper_centers']=int(len(self.lanes.centers))
        state['lane_mapper_spacing']=float(self.lanes.spacing or 0.0)
        state['chicken_forward_spike_rejected']=int(
            self.chicken_forward_spike_last
        )
        state['chicken_forward_spikes_rejected']=int(
            self.chicken_forward_spikes_rejected
        )
        state['crash_forward_spikes_ignored']=int(
            getattr(self.crash,'forward_spikes_ignored',0)
        )

        # V4.2.8: temporary chicken/lane loss must not look like the model
        # forgot everything. Preserve diagnostics, but NEVER preserve GREEN.
        diag_keys = (
            'stage_difficulty_score','stage_profile_support','stage_speed_p95',
            'stage_gap_p25','stage_speed_reference','crash_memory_score',
            'crash_memory_matches','adaptive_confidence','adaptive_required_confidence',
            'czn_speed_reference','pattern_events','regime_samples'
        )
        valid_lane = str(state.get('lane','-')) != '-' and bool(state.get('chicken_ok',False))
        if valid_lane:
            for k in diag_keys:
                if k in state:
                    self.last_valid_diag[k]=state.get(k)
        else:
            for k,v in self.last_valid_diag.items():
                state.setdefault(k,v)
            state['green_evidence_ok']=False
            if chicken is None:
                state['green_evidence_reason']='TRACK HOLD: NO CHICKEN HISTORY'
            elif not self.lanes.ready:
                state['green_evidence_reason']=(f"TRACK HOLD: LANES {self.lanes.source} " f"N{len(self.lanes.centers)} SP{float(self.lanes.spacing or 0):.0f}")
            else:
                state['green_evidence_reason']='TRACK HOLD: NEXT LANE'
            state['frame_tracking_hold']=True

        # A brief visual dropout no longer destroys the entire evidence dwell.
        # Long/ambiguous loss still blocks GREEN.
        if valid_lane and not chicken_trusted:
            state['green_evidence_ok']=False
            state['green_evidence_reason']='VISION HOLD: CHICKEN'
            state['vision_hold']=True
        elif valid_lane and not chicken_fresh:
            state['chicken_short_hold']=True
        elif valid_lane and self.chicken_fresh_streak < 2:
            # One isolated fresh frame after a pan/jump/dropout is not enough
            # to authorize GREEN; require a second consistent observation.
            state['green_evidence_ok']=False
            state['green_evidence_reason']='VISION REACQUIRE'
            state['vision_hold']=True

        # V5.2 target-integrity monitor. Zero vehicle tracks is NOT a failure:
        # an empty lane is a valid safe observation. The previous V5.1 rule
        # self-healed 613 times in ~63 minutes and spent ~27% of states rewarming.
        # We now heal only when the locked target disagrees with the immediate
        # chicken-relative geometric proposal for a sustained period.
        _track_count=int(state.get('active_tracks',0) or 0)
        _motion_ratio=float(state.get('motion_corridor_ratio',1.0) or 0.0)
        _starve_candidate=bool(
            valid_lane and not viewport_unstable and scene_stable
            and bool(state.get('motion_ready',False))
            and _track_count == 0 and _motion_ratio <= .025
            and frame_activity >= float(CFG['tracking'].get('starvation_min_scene_activity',.35))
        )
        _starve_age=0.0
        if _starve_candidate:
            if self._track_starve_since is None:
                self._track_starve_since=perf_now
            _starve_age=max(0.0,perf_now-self._track_starve_since)
        else:
            self._track_starve_since=None

        proposal_x=None
        proposal_err=None
        proposal_ratio=None
        proposal_authoritative=False
        if self._last_target_proposal is not None and self.target_lane_lock.lane_x is not None:
            proposal_x=float(self._last_target_proposal[1])
            spacing=max(40.0,float(self.lanes.spacing or 185.0))
            proposal_err=abs(float(self.target_lane_lock.lane_x)-proposal_x)/spacing
            if chicken is not None:
                proposal_ratio=(proposal_x-float(chicken.get('cx',0.0)))/spacing
                proposal_authoritative=bool(
                    float(CFG['tracking'].get('proposal_sync_min_ahead_fraction',.60))
                    <= proposal_ratio
                    <= float(CFG['tracking'].get('proposal_sync_max_ahead_fraction',1.42))
                )
        mismatch=bool(
            proposal_authoritative
            and proposal_err is not None and proposal_err >= float(CFG['tracking'].get('target_proposal_mismatch_fraction',.32))
            and chicken_fresh and not viewport_unstable and scene_stable
            and not bool(progress_scroll.get('progress_scroll_context',False))
        )
        if mismatch:
            if self._target_mismatch_since is None:
                self._target_mismatch_since=perf_now
        else:
            self._target_mismatch_since=None
        mismatch_age=(0.0 if self._target_mismatch_since is None else max(0.0,perf_now-self._target_mismatch_since))
        _sensor_desync=bool(mismatch and mismatch_age >= float(CFG['tracking'].get('target_proposal_mismatch_seconds',.55)))
        _did_track_heal=False
        if _sensor_desync and self._last_target_proposal is not None:
            if perf_now-self._last_tracking_heal >= float(CFG['tracking'].get('target_geometry_heal_cooldown_seconds',1.0)):
                self.target_lane_lock.force_reanchor([self._last_target_proposal],wall_now,reason='PROPOSAL_SYNC')
                self.motion_roi_lane=None
                self.motion_roi_rect=None
                self.motion_roi_generation += 1
                self.motion_rewarm_until=max(self.motion_rewarm_until,perf_now+float(CFG['tracking'].get('roi_rewarm_seconds',.35)))
                self._last_tracking_heal=perf_now
                self._target_geometry_heals += 1
                _did_track_heal=True
                self._target_mismatch_since=None

        state['scene_frame_activity']=float(frame_activity)
        state['tracking_starvation']=int(_starve_candidate and _starve_age >= float(CFG['tracking'].get('starvation_seconds',2.0)))
        state['tracking_starvation_seconds']=float(_starve_age)
        state['sensor_desync']=int(_sensor_desync)
        state['tracking_self_heals']=int(self._target_geometry_heals)
        state['sensor_desync_heals']=int(self._target_geometry_heals)
        state['tracking_rewarm']=int(_did_track_heal or perf_now < self.motion_rewarm_until)
        state['target_proposal_x']=(None if proposal_x is None else float(proposal_x))
        state['target_proposal_error_ratio']=(None if proposal_err is None else float(proposal_err))
        state['target_proposal_ratio']=(None if proposal_ratio is None else float(proposal_ratio))
        state['target_proposal_authoritative']=int(bool(proposal_authoritative))
        state['confirmed_jump_advances']=int(self._confirmed_jump_advances)
        state['stale_scene_watchdog']=0
        state['stale_scene_recoveries']=int(self._watch_recoveries)
        if _did_track_heal:
            state['green_evidence_ok']=False
            state['green_evidence_reason']='TARGET PROPOSAL SYNC'
            state['viewport_hold']=True

        # V5.2.6 bounded landing advance: recover consumed targets sooner without changing normal target-follow.  V5.2's identity confirmer normally
        # advances the target, but this run showed long TARGET-PHASE holds where
        # the chicken remained on/near the old target (distance ratio ~0.16).
        # Only advance after fresh/stable chicken geometry persists and the lane
        # detector already proposes a valid next lane roughly one spacing ahead.
        _landing_near=False
        _landing_proposal_ok=False
        _landing_recovery=None
        _landing_age=0.0
        try:
            _tr=float(state.get('target_lane_distance_ratio'))
            _landing_near=bool(-.10 <= _tr <= float(CFG['tracking'].get('consumed_target_recovery_max_fraction',.62)))
            if chicken is not None:
                _sp=max(40.0,float(self.lanes.spacing or 185.0))
                _cx=float(chicken.get('cx',0.0))
                if self._last_target_proposal is not None:
                    _px=float(self._last_target_proposal[1])
                    _pr=(_px-_cx)/_sp
                    if (
                        float(CFG['tracking'].get('consumed_target_next_min_fraction',.76)) <= _pr
                        <= float(CFG['tracking'].get('consumed_target_next_max_fraction',1.38))
                        and self.target_lane_lock.lane_x is not None
                        and (_px-float(self.target_lane_lock.lane_x))
                            >= _sp*float(CFG['tracking'].get('consumed_target_min_advance_fraction',.45))
                    ):
                        _landing_recovery=self._last_target_proposal
                if _landing_recovery is None:
                    _landing_recovery=self.target_lane_lock.forward_recovery_candidate(
                        self.lanes.centers, _cx, _sp,
                        min_ratio=float(CFG['tracking'].get('consumed_target_next_min_fraction',.76)),
                        max_ratio=float(CFG['tracking'].get('consumed_target_next_max_fraction',1.38)),
                        min_advance_fraction=float(CFG['tracking'].get('consumed_target_min_advance_fraction',.45)),
                    )
                _landing_proposal_ok=bool(_landing_recovery is not None)
        except Exception:
            _landing_near=False
            _landing_recovery=None
        _landing_candidate=bool(
            _landing_near and _landing_proposal_ok and chicken_fresh
            and self.chicken_fresh_streak >= 3 and self._anchor_stable
            and not viewport_unstable and scene_stable
        )
        if _landing_candidate:
            if self._landing_hold_since is None:
                self._landing_hold_since=perf_now
            _landing_age=max(0.0,perf_now-self._landing_hold_since)
            if _landing_age >= float(CFG['tracking'].get('landing_advance_hold_seconds',.32)):
                self.target_lane_lock.force_reanchor([_landing_recovery],wall_now,reason='CONSUMED_TARGET_ADVANCE')
                self._last_target_proposal=(int(_landing_recovery[0]),float(_landing_recovery[1]))
                self.motion_roi_lane=None
                self.motion_roi_generation += 1
                self.motion_rewarm_until=max(
                    self.motion_rewarm_until,
                    perf_now+float(CFG['tracking'].get('landing_advance_rewarm_seconds',.18))
                )
                self._landing_recoveries += 1
                self._landing_hold_since=None
                state['green_evidence_ok']=False
                state['green_evidence_reason']='CONSUMED TARGET ADVANCE'
                state['target_geometry_hold']=True
        else:
            self._landing_hold_since=None
        state['consumed_target_candidate_x']=(None if _landing_recovery is None else float(_landing_recovery[1]))
        state['consumed_target_hold_age']=float(_landing_age)
        state['consumed_target_recoveries']=int(self._landing_recoveries)

        _fresh_age=(1e9 if self.last_fresh_chicken is None else max(0.0,wall_now-self.last_fresh_chicken_ts))
        _landing_wait=bool(
            str(state.get('target_lane_lock_reason','')) == 'WAIT_CHICKEN_LAND'
            or bool(getattr(self.chicken,'last_midlane_rejected',False))
        )
        _reacquire_age=(
            float(CFG['tracking'].get('post_jump_reacquire_seconds',.60))
            if _landing_wait
            else 1.00
        )

        if _landing_wait:
            if self._landing_wait_since is None:
                self._landing_wait_since=perf_now
        else:
            self._landing_wait_since=None
        _landing_wait_age=(
            0.0 if self._landing_wait_since is None
            else max(0.0,perf_now-self._landing_wait_since)
        )
        _landing_watchdog_recovered=False
        if (
            _landing_wait
            and _landing_wait_age >= float(
                CFG['tracking'].get('landing_wait_watchdog_seconds',1.35)
            )
            and chicken is not None
            and chicken_fresh
            and self.chicken_fresh_streak >= 2
            and self._anchor_stable
            and not viewport_unstable
            and scene_stable
        ):
            _wd_next=self.lanes.next_lanes(float(chicken['cx']),count=1)
            if _wd_next:
                self.target_lane_lock.force_reanchor(
                    _wd_next,wall_now,reason='LANDING_WAIT_RECOVERY'
                )
                self._last_target_proposal=(
                    int(_wd_next[0][0]),float(_wd_next[0][1])
                )
                self.motion_roi_lane=None
                self.motion_roi_rect=None
                self.motion_roi_frame_shape=None
                self.motion_roi_generation += 1
                self.motion_rewarm_until=max(
                    self.motion_rewarm_until,
                    perf_now+float(
                        CFG['tracking'].get(
                            'landing_wait_watchdog_rewarm_seconds',.16
                        )
                    )
                )
                self._landing_wait_watchdog_recoveries += 1
                self._landing_wait_since=None
                _landing_watchdog_recovered=True
                state['green_evidence_ok']=False
                state['green_evidence_reason']='LANDING WAIT RECOVERY'
                state['target_geometry_hold']=True
        _force_chicken=bool(
            not chicken_fresh and _fresh_age >= _reacquire_age
            and not viewport_unstable
            and perf_now-self._last_forced_reacquire >= .75
        )
        if _force_chicken:
            try:
                self.chicken.force_reacquire()
            except AttributeError:
                self.chicken.restore_reference(None)
            self.last_fresh_chicken=None
            self.last_fresh_chicken_ts=0.0
            self.chicken_fresh_streak=0
            self._last_forced_reacquire=perf_now
            self._forced_chicken_reacquires += 1
            state['green_evidence_ok']=False
            state['green_evidence_reason']='CHICKEN REACQUIRE'
            state['vision_hold']=True

        state['post_jump_reacquire_active']=int(bool(_landing_wait))
        state['post_jump_reacquire_age_required']=float(_reacquire_age)
        state['landing_wait_age']=float(_landing_wait_age)
        state['landing_wait_watchdog_recoveries']=int(
            self._landing_wait_watchdog_recoveries
        )
        state['landing_wait_watchdog_recovered']=int(
            bool(_landing_watchdog_recovered)
        )
        state['landing_hold_recoveries']=int(self._landing_recoveries)
        state['forced_chicken_reacquires']=int(self._forced_chicken_reacquires)
        state['chicken_fresh_age']=float(_fresh_age)

        if viewport_unstable:
            state['green_evidence_ok']=False
            state['green_evidence_reason']='VIEWPORT MOVING'
            state['viewport_hold']=True
        elif _did_track_heal:
            pass
        elif perf_now < self.motion_rewarm_until or not state.get('motion_ready',False):
            state['green_evidence_ok']=False
            state['green_evidence_reason']='MOTION REWARM'
            state['viewport_hold']=True

        # Never authorize a jump when the locked target is not the immediate
        # next geometric lane. This is the root cause of several V4.4.0 GREEN
        # failures: the model was analysing a lane 2-5 spacings ahead.
        if (
            chicken is not None
            and not bool(state.get('target_lane_geometry_ok',False))
        ):
            state['green_evidence_ok']=False
            state['green_evidence_reason']='TARGET RELOCK'
            state['target_geometry_hold']=True

        else:
            _target_ratio=state.get('target_lane_distance_ratio')
            try:
                _target_ratio=float(_target_ratio)
            except Exception:
                _target_ratio=None
            _target_min=float(CFG['tracking'].get('target_green_min_ahead_fraction',.64))
            if str(state.get('eta_source','')).lower() in ('slow-before','live-slow-before'):
                _target_min=float(CFG['tracking'].get('target_green_slow_before_min_ahead_fraction',.56))
            _target_max=float(CFG['tracking'].get('target_green_max_ahead_fraction',1.30))
            _target_phase_ok=bool(_target_ratio is not None and _target_min <= _target_ratio <= _target_max)
            state['target_green_geometry_ok']=_target_phase_ok
            state['target_green_min_ratio']=float(_target_min)
            if not _target_phase_ok:
                state['green_evidence_ok']=False
                state['green_evidence_reason']='TARGET PHASE'
                state['target_geometry_hold']=True

        # V5: replace the accumulated V4 soft-threshold stack with an online
        # future-clear-window probability. Hard physical/vision vetoes remain.
        _perf_v5=time.perf_counter()
        self._tick_phase='safe_window_prediction'
        state.update(crossing_occupancy(
            self.motion.last_mask, state.get('target_lane_x'), chicken, self.risk))
        state['detector_max_blob_area']=self.motion.last_effective_max_area
        apply_crossing_guard(state)
        state = self.safe_window_v5.apply(state, wall_now)
        state['decision_frame_timestamp']=wall_now
        state['green_display_deadline']=self.green_display_lease.update(state,wall_now)
        state['green_display_expired']=0
        v5_ms=1000.0*(time.perf_counter()-_perf_v5)
        state['perf_capture_ms']=float(capture_ms)
        state['perf_chicken_ms']=float(chicken_detect_ms)
        state['perf_lane_ms']=float(lane_scan_ms)
        state['perf_motion_ms']=float(motion_ms)
        state['perf_risk_ms']=float(risk_ms)
        state['perf_v5_ms']=float(v5_ms)
        state['perf_preoutcome_ms']=float(1000.0*(time.perf_counter()-tick_started))
        state['performance_recovery_mode']=int(processing_fps < float(CFG['risk'].get('performance_recovery_fps',4.0)))

        self._tick_phase='jump_learning'
        # Manual action-outcome learning.
        # Capture the state BEFORE movement starts. A completed one-lane move
        # is SAFE; a confirmed crash before landing is UNSAFE. This gives the
        # classifier real balanced examples instead of speculative labels.
        cx = (
            None if (
                chicken is None or not chicken_fresh or viewport_unstable
                or perf_now < self.motion_rewarm_until
            )
            else float(chicken.get('cx',0.0))
        )
        if cx is not None:
            spacing=float(self.lanes.spacing or 185.0)
            start_px=max(
                18.0,
                spacing*float(CFG['learning'].get(
                    'manual_action_start_fraction',.055
                ))
            )
            if self.passive_last_x is None:
                self.passive_last_x=cx

            dx=cx-self.passive_last_x
            if self.passive_jump is None:
                # Keep a rolling pre-action snapshot only when the immediate
                # target geometry is sane and the viewport is stable.
                if (
                    bool(state.get('target_green_geometry_ok',False))
                    and bool(state.get('scene_pan_stable',True))
                    and state.get('training_features') is not None
                ):
                    self.passive_pre_state=dict(state)

                if dx >= start_px and self.passive_pre_state is not None:
                    pst=self.passive_pre_state
                    target_dx=float(
                        pst.get('target_lane_distance')
                        or pst.get('next_lane_distance')
                        or spacing
                    )
                    if .65*spacing <= target_dx <= 1.35*spacing:
                        self.passive_jump={
                            'start_ts':wall_now,
                            'start_x':self.passive_last_x,
                            'context':self.learner.safety_context_from_state(pst),
                            'features':list(pst.get('training_features')),
                            'pre_state':pst,
                            'target_dx':target_dx,
                            'target_x':float(pst.get('target_lane_x') or (self.passive_last_x + target_dx)),
                            'viewport_rebase_count':int(self.viewport_rebase_count),
                            'target_switches_at_start':int(self.target_lane_lock.switches),
                            'max_x':cx,
                        }
                        self.passive_stable_since=None
            else:
                self.passive_jump['max_x']=max(
                    self.passive_jump['max_x'],cx
                )
                moved=cx-self.passive_jump['start_x']
                target=self.passive_jump['target_dx']
                # V5.0.4: screen/camera motion can move chicken X by roughly one
                # lane and used to be counted as a successful manual jump.  A real
                # landing must converge on the SAME pre-jump target in a stable
                # viewport; a pan moves chicken and target together and fails this.
                target_x=float(self.passive_jump.get('target_x', self.passive_jump['start_x']+target))
                target_error=abs(float(cx)-target_x)
                same_view=(int(self.passive_jump.get('viewport_rebase_count',-1)) == int(self.viewport_rebase_count))
                landed_on_target=bool(target_error <= .34*max(spacing,target))
                if .72*target <= moved <= 1.35*target and landed_on_target and same_view and chicken_fresh and bool(state.get('scene_pan_stable',True)):
                    if self.passive_stable_since is None:
                        self.passive_stable_since=wall_now
                    elif wall_now-self.passive_stable_since >= .52:
                        if bool(CFG['learning'].get('passive_manual_success_enabled',False)):
                            _start_sw=int(
                                self.passive_jump.get(
                                    'target_switches_at_start',
                                    self.target_lane_lock.switches
                                )
                            )
                            _cur_sw=int(self.target_lane_lock.switches)
                            _unique_switch=bool(
                                _cur_sw == _start_sw + 1
                                and _cur_sw > int(self.last_manual_success_switch)
                            )
                            if _unique_switch:
                                # Supplemental learning only. The model continues
                                # learning traffic/gaps autonomously; a user's
                                # correct jump contributes one low-weight SAFE
                                # sample for that real target ownership change.
                                self.learner.remember_safe_context(
                                    self.passive_jump['context'],timestamp=wall_now,
                                    weight=.32,source='manual_jump_success_unique'
                                )
                                # Do not make user play responsible for keeping
                                # the classifier alive. Manual success is merely
                                # supplemental. When processing is already in
                                # degraded-FPS mode, keep the cheap SAFE-context
                                # memory but skip the heavier partial_fit update.
                                if not bool(processing_degraded):
                                    self.learner.learn_outcome(
                                        self.passive_jump['features'],0,
                                        weight=.38,source='manual_jump_success_unique'
                                    )
                                else:
                                    self.manual_success_context_only += 1
                                self.manual_lane_successes += 1
                                self.last_manual_success_switch=_cur_sw
                                self.last_crash_notice=(
                                    f"MANUAL SAFE +{self.manual_lane_successes}"
                                )
                                self.last_crash_notice_until=wall_now+2.0
                            else:
                                self.manual_success_duplicate_skips += 1
                        # V5.2.9: GREEN outcome ownership is separate from the
                        # optional passive/manual training feature. V5.2.8 had
                        # passive_manual_success_enabled=false, so the bridge
                        # below never ran and GREEN successes stayed at zero.
                        green_success_evt = self.outcome.confirm_validated_manual_success(
                            fresh_chicken, wall_now
                        )
                        if green_success_evt is not None:
                            self._handle_green_outcome(green_success_evt)
                        # V5.0.4: do not serialize the full learner on every
                        # validated jump. The periodic 8s save already protects
                        # state; per-jump flushes caused long-session FPS decay.
                        self.passive_jump=None
                        self.passive_stable_since=None
                        self.passive_pre_state=None
                elif (
                    moved > 1.60*target
                    or wall_now-self.passive_jump['start_ts'] > float(
                        CFG['learning'].get('manual_action_timeout_seconds',4.8)
                    )
                ):
                    self.passive_jump=None
                    self.passive_stable_since=None
                    self.passive_pre_state=None
            self.passive_last_x=cx

        self._tick_phase='opportunity_learning'
        # Retrospective SAFE-opportunity learning.
        # If a candidate lane remains threat-free for longer than a physical
        # one-lane jump window, that starting state is a low-weight SAFE example
        # even when the user did not jump.
        for c in list(self.safe_candidates):
            if c.get('invalid'):
                continue
            if (
                str(state.get('lane','-')) != str(c['lane'])
                or state.get('visible_threat',False)
                or int(state.get('uncertain_incoming_count',0))>0
                or float(state.get('motion_corridor_ratio',1.0)) >
                    float(CFG['learning'].get('opportunity_max_motion_ratio',.055))
                or float(state.get('raw_risk',state.get('risk',50))) > 55
            ):
                c['invalid']=True
                continue
            if wall_now >= c['deadline']:
                # Observation-only gap. Do NOT call this a supervised SAFE jump:
                # no chicken actually crossed, and the latest run generated 628
                # speculative SAFE labels versus only 7 acted failures. Traffic
                # timing is already learned by events/motion; supervised SAFE is
                # reserved for an actual successful manual/GREEN jump.
                c['done']=True

        self.safe_candidates=deque(
            [c for c in self.safe_candidates if not c.get('done') and
             wall_now-c['start_ts']<2.0],
            maxlen=12
        )

        lane_now=state.get('lane','-')
        feat_now=state.get('training_features')
        candidate_ok=bool(
            processing_healthy
            and chicken_fresh
            and str(lane_now)!='-'
            and feat_now is not None
            and bool(state.get('czn_calibrated',False))
            and bool(state.get('lane_visibility_ok',False))
            and bool(state.get('motion_corridor_clear',False))
            and not bool(state.get('visible_threat',False))
            and int(state.get('uncertain_incoming_count',0))==0
            and float(state.get('raw_risk',state.get('risk',50))) <=
                float(CFG['learning'].get('opportunity_max_raw_risk',12.0))
            and float(state.get('motion_clear_dwell',0.0)) >=
                float(CFG['learning'].get('opportunity_min_motion_dwell',.45))
            and float(state.get('effective_eta') or 0.0) >=
                float(CFG['learning'].get('opportunity_min_eta_seconds',1.0))
        )
        lane_key=str(lane_now)
        if candidate_ok and wall_now-self.last_safe_candidate_ts.get(lane_key,0.0) >= \
                float(CFG['learning'].get('opportunity_sample_interval_seconds',1.25)):
            horizon=float(CFG['learning'].get(
                'opportunity_verification_seconds',
                CFG['risk'].get('jump_crossing_seconds',.55)
                + CFG['risk'].get('safety_buffer_seconds',.30)
                + .15
            ))
            self.safe_candidates.append({
                'start_ts':wall_now,'deadline':wall_now+horizon,
                'lane':lane_now,'features':list(feat_now),
                'context':self.learner.safety_context_from_state(state),
                'invalid':False,'done':False
            })
            self.last_safe_candidate_ts[lane_key]=wall_now

        # Evidence must remain safe for a dwell period. Any lane/source/track/
        # pattern change resets that dwell instead of showing instant GREEN.
        eta_src = str(state.get('eta_source','unknown'))
        pattern_key = ((state.get('lane1') or {}).get('pattern',{}).get('sequence','-')
                       if eta_src == 'pattern' else '-')
        dynamic_gap_key = (
            state.get('dynamic_gap_cycle_id','-')
            if eta_src == 'dynamic-gap' else '-'
        )
        evidence_key = (
            f"{state.get('lane','-')}|{eta_src}|"
            f"{state.get('threat_id') or '-'}|{pattern_key}|{dynamic_gap_key}"
        )

        # V4.4.10: admission guard for repeated *unacted* GREENs.
        # Keep the predictor/risk/learning logic intact; only suppress a new
        # display signal until the previous ignored signal has re-armed.
        # V4.4.11: use the outcome tracker's own admission state as the
        # single authority. green_display_allowed() already returns True for
        # a genuinely active current signal. The old `indicator.state ==
        # CLEAR` escape clause could bypass re-arm while CLEAR flickered.
        # V5.2.4: the indicator must know about one-jump/rearm UI blocks BEFORE
        # it decides CLEAR. Previously indicator could internally consume a V5
        # gap and then block_ui_state() hid that CLEAR afterwards; later frames
        # were rejected as 'GAP ALREADY SIGNALED' even though the user never saw it.
        state['green_rearm_min_busy']=self.risk.gap_open_min_busy
        pre_ui_block_state = self.outcome.block_ui_state()
        signal_admission_open = bool(
            self.outcome.green_display_allowed(wall_now,state.get('dynamic_gap_cycle_id'),state=state)
            and pre_ui_block_state is None
        )
        state['signal_admission_open'] = int(signal_admission_open)
        state['signal_admission_reason'] = (
            '' if signal_admission_open
            else ('ONE JUMP ONLY - RECHECK NEXT LANE' if pre_ui_block_state is not None
                  else (self.outcome.missed_green_rearm.reason or 'WAIT AFTER UNACTED GREEN'))
        )

        state['green_missed_rearm_reason']=self.outcome.missed_green_rearm.reason
        state['green_missed_rearm_busy_cycle']=self.outcome.missed_green_rearm.busy_cycle
        state['green_missed_rearm_ready_cycle']=self.outcome.missed_green_rearm.ready_cycle
        feat=state.get('training_features')
        if feat is not None and not viewport_unstable:
            self.precrash.append({
                'timestamp': wall_now, 'features': list(feat),
                'raw_risk': float(state.get('risk',50)),
                'display_risk': float(self.indicator.display_risk),
                'lane': state.get('lane','-'),
                'pattern': state.get('pattern_text',''),
                'safety_context': self.learner.safety_context_from_state(state),
            })

        self._tick_phase='outcome_validation'
        learning_chicken=(
            None if (
                viewport_unstable or perf_now < self.motion_rewarm_until
            ) else fresh_chicken
        )
        # V5.5.0: outcome ownership needs the fresh chicken even while the
        # traffic/motion ROI is rewarming after a jump. V5.4.9 passed None here
        # during exactly the landing frames where target ownership advanced,
        # causing real landings to miss success validation and later resets to
        # be blamed on the original GREEN. Coordinate-frame instability still
        # blocks outcome attribution.
        outcome_chicken=(None if viewport_unstable else fresh_chicken)
        crash_event=self.crash.update(learning_chicken,frame.shape[1],wall_now)

        # V5.3.8 SECONDARY FULLSCREEN-REFRAME SAFETY NET.
        # At low FPS the visual gate can miss a cut spread across several frames.
        # Before ANY crash/ GREEN-failure learning, reinterpret a confirmed
        # ~two-lane reset-to-first-lane as the game's normal progress reframe.
        if crash_event and self.fullscreen_reframe_mode:
            _sp=self.lanes.spacing
            if _sp is None:
                _refw=float(CFG['lanes'].get('reference_width_px',1280.0))
                _base=float(CFG['lanes'].get('divider_expected_spacing_px',221.0))
                _sp=_base*(float(frame.shape[1])/max(1.0,_refw))
            _crf=self.fullscreen_reframe.classify_crash_event(
                crash_event,_sp,frame.shape[1],perf_now
            )
            if bool(_crf.get('detected',False)):
                self.crash.suppress_last_crash_as_progress_reframe(
                    fresh_chicken,wall_now
                )
                self._apply_fullscreen_progress_reframe(
                    float(_crf.get('dx',0.0)),fresh_chicken,
                    frame.shape[1],wall_now,perf_now
                )
                progress_scroll=self._progress_scroll_state_from_reframe(
                    perf_now,detected=True
                )
                scene_stable=False
                viewport_unstable=True
                learning_chicken=None
                signal_admission_open=False
                state['green_evidence_ok']=False
                state['green_evidence_reason']='FULLSCREEN PROGRESS REFRAME'
                state['clear_block_reason']='FULLSCREEN PROGRESS REFRAME'
                state['game_progress_scroll_active']=1
                state['game_progress_scroll_settling']=1
                state['game_progress_scroll_context']=1
                state['game_progress_scroll_count']=int(
                    progress_scroll.get('progress_scroll_count',0)
                )
                state['game_progress_scroll_age']=0.0
                state['fullscreen_reframe_active']=1
                state['fullscreen_reframe_count']=int(_crf.get('count',0))
                state['fullscreen_reframe_shift_px']=float(_crf.get('dx',0.0))
                state['fullscreen_reframe_shift_lanes']=float(
                    _crf.get('shift_lanes',0.0)
                )
                state['fullscreen_reframe_age']=0.0
                crash_event=None

        # Apply after V5 and all recovery overrides, immediately before admission.
        # Existing required horizon already includes jump, buffer and latency.
        if chicken is not None and state.get('lane1') is not None:
            _lane=state['lane1']
            state['upstream_prediction_clock']=time.perf_counter()
            _prediction_tracks=self.motion.prediction_tracks()
            state['upstream_trajectory_evidence']=[{k:t.get(k) for k in (
                'id','cx','cy','h','w','vy','fit_vy','net_vy','ts','age',
                'missing','matched','direction_valid','direction_suspicious','history'
            )} for t in _prediction_tracks]
            _arrival,_vehicle=predict_arrival(
                _prediction_tracks,chicken,int(state['lane']),float(state['target_lane_x']),
                self.lanes,self.risk,state['upstream_prediction_clock'])
            apply_guard(state,_arrival,_vehicle,float(state.get(
                'dynamic_gap_required_eta',self.risk.jump_delay+self.risk.jump_time+self.risk.safety)))

        if chicken is not None and state.get('lane1') is not None:
            _unresolved=unresolved_vehicle(_prediction_tracks,chicken,
                float(state['target_lane_x']),self.risk,state['upstream_prediction_clock'],
                float(state.get('dynamic_gap_required_eta') or (self.risk.jump_delay+self.risk.jump_time+self.risk.safety)))
            apply_unresolved_guard(state,_unresolved)

        apply_crossing_guard(state)
        _deadline=state.get('green_display_deadline')
        if _deadline is not None and time.time()>=float(_deadline):
            state['green_evidence_ok']=False
            state['green_evidence_reason']='ACTION LEASE EXPIRED'
        _indicator_eta_override=required_eta_override_for_state(state)
        state['indicator_required_eta_override']=(
            None if _indicator_eta_override is None else float(_indicator_eta_override)
        )
        if crash_event:
            # If a manual action had actually started, this is a real UNSAFE
            # example from the pre-action state. Do not use unrelated deaths.
            if self.passive_jump is not None:
                if self.passive_jump.get('late_after_green'):
                    # V4.4.11: a late GREEN reaction remains excluded from
                    # direct GREEN supervised classification, but if the SAME
                    # unresolved manual jump then crashes it is no longer
                    # timing-only evidence. Learn the actual action-onset state
                    # as unsafe and penalize only the originating GREEN source.
                    used_manual_fail=self.learner.learn_manual_lane_failure(
                        self.passive_jump,timestamp=wall_now
                    )
                    # V5.3.6: once the displayed GREEN has expired beyond the
                    # tight attribution grace, the later jump is timing-only. It
                    # may still be a real manual crash, but it must NOT poison the
                    # old GREEN source or V5 failure memory.
                    used_source_fail=0
                    if used_manual_fail:
                        self.manual_failures += 1
                        self.last_crash_notice=(
                            f"LATE ACTION CRASH (GREEN NOT BLAMED) "
                            f"MF+{self.manual_failures}"
                        )
                        self.last_crash_notice_until=wall_now+3.5
                        self.learner.flush(save_model=False)
                else:
                    used_manual_fail=self.learner.learn_manual_lane_failure(
                        self.passive_jump,timestamp=wall_now
                    )
                    if used_manual_fail:
                        self.manual_failures += 1
                        self.last_crash_notice=(
                            f"MANUAL FAIL +{self.manual_failures} LEARNED"
                        )
                        self.last_crash_notice_until=wall_now+3.0
            self.passive_jump=None
            self.passive_stable_since=None
            self.passive_pre_state=None
            self.safe_candidates.clear()
            self.learner.reset_pattern_timing(crash_event.get('reason','crash'))
            self.risk.notify_crash(crash_event)
            # A GREEN failure is recorded ONLY when the chicken actually moved
            # in response to that GREEN and then died.
            green_failure = self.outcome.on_crash(crash_event, wall_now)
            if green_failure is not None:
                self._handle_green_outcome(green_failure)
            self._learn_crash_event(crash_event)
            # A confirmed failure becomes an immediate red/high-risk sample.
            ind=self.indicator.update(
                99.0, visible_threat=True,
                eta=state.get('effective_eta', state.get('tti')),
                eta_source=state.get('eta_source','unknown'),
                external_gate_ok=(state.get('green_evidence_ok', False) and signal_admission_open),
                external_block_reason=(
                    'PROCESSING STALL' if not processing_healthy
                    else (state.get('signal_admission_reason','') or state.get('green_evidence_reason',''))
                ),
                required_eta_override=_indicator_eta_override,
                evidence_key=evidence_key,
                now=perf_now
            )
        else:
            ind=self.indicator.update(
                state.get('risk',50),
                state.get('visible_threat',False),
                eta=state.get('effective_eta', state.get('tti')),
                eta_source=state.get('eta_source','unknown'),
                external_gate_ok=(state.get('green_evidence_ok', False) and signal_admission_open),
                external_block_reason=(
                    'PROCESSING STALL' if not processing_healthy
                    else (state.get('signal_admission_reason','') or state.get('green_evidence_reason',''))
                ),
                required_eta_override=_indicator_eta_override,
                evidence_key=evidence_key,
                now=perf_now
            )
        state.update(ind)

        # Do not create scroll ownership while CrashDetector is deciding reset.
        state['reset_candidate_pending']=int(self.crash.pending is not None)
        state['reset_confirmed_this_tick']=int(crash_event is not None)
        state=expire_state(state,time.time())

        # GREEN -> ACTION -> SUCCESS/FAILURE validation.
        for evt in self.outcome.update(state, outcome_chicken, wall_now):
            if evt.get('kind')!='green_outcome':
                with (self.learner.folder/'signal_audit_v558.jsonl').open('a',encoding='utf-8') as audit:
                    audit.write(json.dumps({**evt,'event_ts':evt.get('event_ts',wall_now),
                        'chicken_x':state.get('chicken_x',None if chicken is None else chicken.get('cx')),
                        'chicken_y':None if chicken is None else chicken.get('cy'),
                        'lane':state.get('lane'),'target_lane_switches':state.get('target_lane_switches'),
                        'cycle_id':state.get('dynamic_gap_cycle_id'),
                        **{k:state.get(k) for k in ('crossing_motion_available', 'crossing_motion_clear', 'crossing_motion_ratio', 'crossing_motion_reason', 'dynamic_gap_unlatched_lower_bound', 'detector_max_blob_area', 'upstream_trajectory_evidence', 'upstream_prediction_clock','upstream_unresolved_vehicle','upstream_uncertainty_would_block','upstream_uncertainty_enforced')}})+'\n')
            if evt.get('kind') == 'green_outcome':
                self._handle_green_outcome(evt)
            elif evt.get('kind') == 'late_unattributed_action':
                used_delay=self.learner.record_late_action_observation(evt)
                if used_delay:
                    self.late_reaction_observations += 1
                    self.learner.flush(save_model=False)
                if self.passive_jump is not None:
                    self.passive_jump['late_after_green']=True
                    self.passive_jump['late_green_delay']=evt.get(
                        'action_delay_from_start'
                    )
                    self.passive_jump['late_green_source']=evt.get(
                        'eta_source','unknown'
                    )
                    self.passive_jump['late_green_eta']=evt.get('eta')
                    self.passive_jump['late_green_lane']=evt.get('lane')
                    self.passive_jump['late_green_signal_id']=evt.get('signal_id')
                self.last_crash_notice = (
                    f"LATE ACTION OBS "
                    f"{evt.get('action_delay_from_start',0):.2f}s"
                )
                self.last_crash_notice_until = time.time() + 2.5

        outcome_status = self.outcome.status()

        # A GREEN is permission for ONE jump only. During motion, provisional
        # landing and re-arm, suppress any fresh green shown by the raw indicator.
        block_state = self.outcome.block_ui_state()
        if block_state is not None:
            state['indicator_state'] = block_state
            state['green_confirmed'] = False
            state['clear_block_reason'] = 'ONE JUMP ONLY - RECHECK NEXT LANE'

        state.update(
            objects=len(tracks), detections=self.motion.last_detection_count,
            fg_pct=self.motion.last_foreground_ratio*100.0,
            fast=sum(self.learner.is_fast(t['speed']) for t in tracks),
            observations=self.learner.observation_n, lanes=len(self.lanes.centers),
            lanes_ready=self.lanes.ready, lane_source=getattr(self.lanes,'source','-'),
            chicken_conf=0.0 if chicken is None else chicken.get('confidence',0.0),
            chicken_fresh=int(bool(chicken_fresh)),
            chicken_x=0.0 if chicken is None else chicken.get('cx',0.0),
            chicken_y=0.0 if chicken is None else chicken.get('cy',0.0),
            crashes=self.crash.crash_count,
            crash_samples=self.learner.crash_sample_n,
            crashes_learned=self.learner.crash_count,
            run_events=max(
                0,int(self.learner.pattern_event_n)-self.run_pattern_start
            ),
            manual_successes=self.manual_lane_successes,
            manual_success_duplicate_skips=self.manual_success_duplicate_skips,
            last_manual_success_switch=self.last_manual_success_switch,
            manual_success_context_only=self.manual_success_context_only,
            manual_failures=self.manual_failures,
            late_reaction_observations=self.late_reaction_observations,
            green_failures=self.learner.green_failure_n,
            green_successes=self.learner.green_success_n,
            green_signals=outcome_status.get('green_signals',0),
            green_acted=outcome_status.get('acted_signals',0),
            green_active=outcome_status.get('active_green_attempt',0),
            green_outcome_successes=outcome_status.get('green_outcome_successes',0),
            green_outcome_failures=outcome_status.get('green_outcome_failures',0),
            visible_green_signal_id=outcome_status.get('visible_green_signal_id'),
            pending_green_signal_id=outcome_status.get('pending_green_signal_id'),
            green_viewport_rebases=outcome_status.get('green_viewport_rebases',0),
            green_chained=outcome_status.get('green_chained',0),
            green_late_unattributed=outcome_status.get('green_late_unattributed',0),
            green_viewport_invalidated=outcome_status.get('green_viewport_invalidated',0),
            green_crash_fallback_ignored=outcome_status.get('green_crash_fallback_ignored',0),
            green_multi_jump_unvalidated=outcome_status.get('green_multi_jump_unvalidated',0),
            green_target_arrival_successes=outcome_status.get('green_target_arrival_successes',0),
            green_progress_handoffs=outcome_status.get('green_progress_handoffs',0),
            green_rearm_geometry_releases=outcome_status.get('green_rearm_geometry_releases',0),
            post_green_action_grace=outcome_status.get('post_green_action_grace',0.18),
            rearm_needed=outcome_status.get('rearm_needed',0),
            expected_jump_px=outcome_status.get('expected_jump_px',0),
            crash_notice=self.last_crash_notice if wall_now < self.last_crash_notice_until else '',
        )
        if state.get('crash_notice'):
            state['pattern_text']=state['crash_notice'] + ' | ' + str(state.get('pattern_text',''))

        state=expire_state(state,time.time())
        self.green_expiry_timer.stop()
        if state.get('indicator_state')=='CLEAR' and state.get('green_display_deadline') is not None:
            self.green_expiry_timer.start(max(1,math.ceil(1000*(
                float(state['green_display_deadline'])-time.time()))))
        self._tick_phase='state_logging'
        state['model_checkpoint_ok']=self.learner.last_model_save_ok
        state['model_checkpoint_ts']=self.learner.last_model_save_ts
        state['model_checkpoint_error']=self.learner.last_model_save_error
        state['runtime_tick_errors']=self._tick_error_count
        state['runtime_tick_error_phase']=''
        state['runtime_tick_error_type']=''
        # Present before CSV/debug I/O. repaint() paints synchronously on the
        # GUI thread, so an expiring cue cannot wait behind queued disk work.
        self._tick_phase='presentation'
        state['input_foreground']=self.input_audit.foreground()
        self.last=expire_state(state,time.time())
        self.ui.repaint()
        state=self.last
        self._notify_indicator_transition(state, time.time())
        if self.ui.presentation_events:
            with (self.learner.folder/'presentation_audit_v5518.jsonl').open('a',encoding='utf-8') as audit:
                for event in self.ui.presentation_events:
                    audit.write(json.dumps(event)+'\n')
            self.ui.presentation_events.clear()
        self._tick_phase='state_logging'
        # V2.8 decision-layer logging: separate from the large raw tracker CSV.
        self.learner.log_state(state, chicken, tracks, crash_event=crash_event)
        if crash_event:
            self.learner.flush(save_model=False)

        self._tick_phase='presentation'
        self._save_debug(frame,tracks,chicken,state)
        if wall_now-self.last_save>CFG['learning']['save_every_seconds']:
            idle_due=idle_checkpoint_due(state,wall_now,self._last_idle_model_checkpoint)
            explicit_save=bool(CFG['learning'].get('save_model_during_run',False))
            self.learner.flush(save_model=explicit_save)
            if idle_due:
                if not explicit_save:
                    self.learner.request_checkpoint()
                self._last_idle_model_checkpoint=wall_now
            self.last_save=wall_now

    def stop(self):
        self.input_audit.close()
        try:
            self.safe_window_v5.save()
        except Exception:
            pass
        self.learner.flush(); self.capture.close()


def main():
    app=QApplication(sys.argv); runner=App()
    try: sys.exit(app.exec())
    finally: runner.stop()

if __name__=='__main__': main()
