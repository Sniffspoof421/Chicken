import cv2
import numpy as np


class ChickenDetector:
    """Visual chicken localizer with robust position confirmation.

    V3.1 separates a raw visual candidate from the CONFIRMED chicken position.
    Normal lane-to-lane motion is accepted quickly, while implausibly large
    teleports must persist for several observations before they can change the
    confirmed position. This prevents one bad frame from poisoning progress /
    crash learning.
    """

    def __init__(self, cfg):
        self.y_min_ratio = float(cfg.get('y_min_ratio', .34))
        self.y_max_ratio = float(cfg.get('y_max_ratio', .61))
        self.smoothing = float(cfg.get('position_smoothing', .55))
        self.max_smooth_distance = float(cfg.get('max_smooth_distance_px', 150))
        self.max_position_jump = float(cfg.get('max_position_jump_px', 260))
        self.jump_confirm_frames = int(cfg.get('jump_confirm_frames', 3))
        self.jump_confirm_radius = float(cfg.get('jump_confirm_radius_px', 85))
        self.max_missing = int(cfg.get('max_missing_frames', 14))
        self.min_red = int(cfg.get('min_red_pixels', 90))
        self.min_yellow = int(cfg.get('min_yellow_pixels', 80))
        self.min_white = int(cfg.get('min_white_pixels', 700))
        self.roi_margin_ratio = float(cfg.get('vertical_roi_margin_ratio', .05))
        self.reference_width = float(cfg.get('reference_width_px', 1280.0))
        self.reference_height = float(cfg.get('reference_height_px', 624.0))
        self.max_geometry_scale = float(cfg.get('max_geometry_scale', 3.0))
        # V5.2 identity lock: an apparent move of roughly one lane used to be
        # accepted immediately because the absolute max_position_jump scaled up
        # with resolution. Logs showed ~88% of such moves snapping back within
        # one second, typically to/from the same static colour blob. Large
        # lane-relative moves now require multi-frame confirmation.
        self.lane_spacing_hint = None
        self.large_move_confirm_fraction = float(cfg.get('large_move_confirm_fraction', .52))
        self.large_move_min_px = float(cfg.get('large_move_min_px', 150.0))
        self.prefer_near_fraction = float(cfg.get('prefer_near_fraction', .24))
        self.midlane_reject_min_fraction = float(
            cfg.get('midlane_reject_min_fraction', .28)
        )
        self.midlane_reject_max_fraction = float(
            cfg.get('midlane_reject_max_fraction', .70)
        )
        self.midlane_rejections = 0
        self.last_midlane_rejected = False
        # V5.2.4: run HSV/contour work on a reduced copy of the chicken band.
        # Returned coordinates/counts are normalized back to full resolution.
        # This preserves identity geometry while materially reducing sustained CPU load.
        self.detection_work_scale = float(np.clip(cfg.get('detection_work_scale', .68), .50, 1.0))

        self.last = None
        self.missing = 0
        self.last_candidates = 0
        self.pending_jump = None
        self.raw_last = None


    def set_lane_spacing(self, spacing):
        try:
            v=float(spacing)
        except Exception:
            v=0.0
        self.lane_spacing_hint = v if v >= 80.0 else None

    def _identity_gate_distance(self, geom_scale):
        absolute = self.max_position_jump * float(geom_scale)
        if self.lane_spacing_hint is None:
            return absolute
        lane_gate=max(self.large_move_min_px*float(geom_scale),
                      self.large_move_confirm_fraction*float(self.lane_spacing_hint))
        return min(absolute,lane_gate)

    def restore_reference(self, reference):
        """Restore the last trusted chicken position after a false teleport.

        Large persistent colour matches near the right edge can survive the
        normal multi-frame teleport confirmer.  Main performs an additional
        lane-scale forward-step sanity check; when that rejects a candidate we
        must also restore the detector's internal reference so the real chicken
        is accepted again immediately on the next frame.
        """
        if reference is None:
            return
        self.last = dict(reference)
        self.pending_jump = None
        self.missing = 0

    def force_reacquire(self):
        """Drop stale positional hysteresis and accept the next visual chicken.

        Used only after a prolonged fresh-detection drought while the viewport is
        stable. This prevents a held pre-jump coordinate from surviving until the
        user manually nudges the game screen.
        """
        self.last = None
        self.raw_last = None
        self.pending_jump = None
        self.missing = 0

    def rebase_viewport(self, dx):
        """Translate stored screen-X state after a camera/view drag.

        Without this, the next genuine chicken detection can look like a huge
        jump/teleport and the detector may hold the old coordinate until the
        user moves the viewport again.
        """
        dx=float(dx or 0.0)
        if abs(dx) < 1e-6:
            return
        def shift_box(obj):
            if obj is None:
                return
            if 'cx' in obj: obj['cx']=float(obj['cx'])+dx
            if 'x' in obj: obj['x']=float(obj['x'])+dx
        shift_box(self.last)
        shift_box(self.raw_last)
        if self.pending_jump is not None:
            self.pending_jump['cx_sum']=float(self.pending_jump.get('cx_sum',0.0))+dx*int(self.pending_jump.get('count',1))
            shift_box(self.pending_jump.get('best'))

    @staticmethod
    def _masks(hsv):
        white = cv2.inRange(hsv, np.array([0,0,165],np.uint8), np.array([179,88,255],np.uint8))
        r1 = cv2.inRange(hsv, np.array([0,105,85],np.uint8), np.array([15,255,255],np.uint8))
        r2 = cv2.inRange(hsv, np.array([164,100,85],np.uint8), np.array([179,255,255],np.uint8))
        red = cv2.bitwise_or(r1,r2)
        yellow = cv2.inRange(hsv, np.array([15,75,100],np.uint8), np.array([43,255,255],np.uint8))
        return white, red, yellow

    def _confirm_candidate(self, best):
        """Return confirmed position, or hold old position while a teleport is verified."""
        self.raw_last = dict(best)

        if self.last is None:
            self.pending_jump = None
            self.last = dict(best)
            return dict(best)

        dx = float(best['cx']) - float(self.last['cx'])
        dy = float(best['cy']) - float(self.last['cy'])
        dist = float(np.hypot(dx, dy))
        self.last_midlane_rejected = False
        geom_scale = float(best.get('geom_scale', 1.0))
        max_position_jump = self._identity_gate_distance(geom_scale)
        max_smooth_distance = self.max_smooth_distance * geom_scale
        jump_confirm_radius = self.jump_confirm_radius * geom_scale

        # Reject ambiguous between-lane identity drift. Real jumps are held at
        # the old trusted lane until a near-full-lane landing candidate appears.
        if self.lane_spacing_hint is not None:
            frac=abs(dx)/max(1.0,float(self.lane_spacing_hint))
            if (
                self.midlane_reject_min_fraction
                <= frac
                <= self.midlane_reject_max_fraction
            ):
                self.midlane_rejections += 1
                self.last_midlane_rejected = True
                held=dict(self.last)
                held['detected']=False
                held['pending_position']=True
                held['midlane_rejected']=True
                held['confidence']=min(float(held.get('confidence',.5)),.50)
                return held

        # Position limits are resolution-aware.
        if dist <= max_position_jump:
            self.pending_jump = None
            if dist <= max_smooth_distance:
                a = self.smoothing
                for k in ('cx', 'cy'):
                    best[k] = (1-a) * float(self.last[k]) + a * float(best[k])
                best['x'] = float(best['cx']) - float(best['w']) / 2.0
                best['y'] = float(best['cy']) - float(best['h']) / 2.0
            self.last = dict(best)
            return dict(best)

        # Large apparent teleport/reset: require a cluster of consistent
        # observations near the NEW point before moving the confirmed position.
        if self.pending_jump is None:
            self.pending_jump = {
                'count': 1,
                'cx_sum': float(best['cx']),
                'cy_sum': float(best['cy']),
                'best': dict(best),
            }
        else:
            pcx = self.pending_jump['cx_sum'] / self.pending_jump['count']
            pcy = self.pending_jump['cy_sum'] / self.pending_jump['count']
            if np.hypot(float(best['cx']) - pcx, float(best['cy']) - pcy) <= jump_confirm_radius:
                self.pending_jump['count'] += 1
                self.pending_jump['cx_sum'] += float(best['cx'])
                self.pending_jump['cy_sum'] += float(best['cy'])
                self.pending_jump['best'] = dict(best)
            else:
                self.pending_jump = {
                    'count': 1,
                    'cx_sum': float(best['cx']),
                    'cy_sum': float(best['cy']),
                    'best': dict(best),
                }

        if self.pending_jump['count'] >= self.jump_confirm_frames:
            p = self.pending_jump
            accepted = dict(p['best'])
            accepted['cx'] = p['cx_sum'] / p['count']
            accepted['cy'] = p['cy_sum'] / p['count']
            accepted['x'] = accepted['cx'] - accepted['w'] / 2.0
            accepted['y'] = accepted['cy'] - accepted['h'] / 2.0
            accepted['confirmed_teleport'] = True
            self.last = dict(accepted)
            self.pending_jump = None
            return accepted

        held = dict(self.last)
        held['detected'] = False
        held['pending_position'] = True
        held['confidence'] = min(float(held.get('confidence', .5)), .55)
        return held

    def detect(self, frame):
        h, w = frame.shape[:2]

        # V4.3.2: all chicken geometry is scaled from the original 1280x624
        # tuning resolution. V4.3.1 rejected the real chicken at ~2x capture
        # resolution because its contour exceeded fixed 190x160 limits.
        sx = float(w) / max(1.0, self.reference_width)
        sy = float(h) / max(1.0, self.reference_height)
        geom_scale = float(np.clip(np.sqrt(max(.01, sx*sy)), .70, self.max_geometry_scale))
        area_scale = geom_scale * geom_scale

        # Expensive HSV/mask work is restricted to the vertical band where the
        # chicken can exist. Global coordinates are restored before returning.
        y0 = max(0, int(h * max(0.0, self.y_min_ratio-self.roi_margin_ratio)))
        y1 = min(h, int(h * min(1.0, self.y_max_ratio+self.roi_margin_ratio)))
        work_full = frame[y0:y1]
        if work_full.size == 0:
            return None
        work_scale = float(self.detection_work_scale)
        if work_scale < .999:
            work = cv2.resize(work_full, None, fx=work_scale, fy=work_scale, interpolation=cv2.INTER_AREA)
        else:
            work = work_full
        coord_scale = 1.0 / max(.01, work_scale)
        count_norm = coord_scale * coord_scale

        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
        white, red, yellow = self._masks(hsv)
        seed = cv2.bitwise_or(red, yellow)
        seed = cv2.dilate(seed, np.ones((7,7),np.uint8), iterations=1)
        seed = cv2.morphologyEx(seed, cv2.MORPH_CLOSE, np.ones((11,11),np.uint8), iterations=2)
        cnts, _ = cv2.findContours(seed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        cand = []
        rh = work.shape[0]
        for c in cnts:
            x, ly, bw, bh = cv2.boundingRect(c)
            fbw = float(bw) * coord_scale
            fbh = float(bh) * coord_scale
            cx = (float(x) + float(bw)/2.0) * coord_scale
            lcy = (float(ly) + float(bh)/2.0) * coord_scale
            cy = y0 + lcy
            if not (h*self.y_min_ratio <= cy <= h*self.y_max_ratio):
                continue
            if fbw < max(8,int(7*geom_scale)) or fbh < max(6,int(6*geom_scale)):
                continue
            if fbw > int(205*geom_scale) or fbh > int(180*geom_scale):
                continue

            pad_full = max(35*geom_scale, min(85*geom_scale, .55*max(fbw,fbh)))
            pad = int(max(1, round(pad_full * work_scale)))
            ww = work.shape[1]
            xa, xb = max(0,x-pad), min(ww,x+bw+pad)
            ya, yb = max(0,ly-pad), min(rh,ly+bh+pad)

            wn = int(round(np.count_nonzero(white[ya:yb,xa:xb]) * count_norm))
            rn = int(round(np.count_nonzero(red[ya:yb,xa:xb]) * count_norm))
            yn = int(round(np.count_nonzero(yellow[ya:yb,xa:xb]) * count_norm))
            rn_local = int(round(np.count_nonzero(red[ly:ly+bh,x:x+bw]) * count_norm))
            yn_local = int(round(np.count_nonzero(yellow[ly:ly+bh,x:x+bw]) * count_norm))

            count_scale = max(.75, min(2.5, area_scale ** .65))
            if (rn < int(self.min_red*count_scale)
                    or yn < int(self.min_yellow*count_scale)
                    or wn < int(self.min_white*count_scale)):
                continue
            if (rn_local < max(int(38*geom_scale), int(self.min_red*.42*count_scale))
                    or yn_local < int(22*geom_scale)):
                continue
            if rn_local / max(1.0, float(yn_local)) < 0.08:
                continue

            score = 20.0*rn_local + 2.5*rn + 0.9*yn_local + 0.35*yn + 0.55*wn
            body_cx = cx - 0.08*max(70.0, fbw)
            est_w = max(60.0*geom_scale, min(160.0*geom_scale, 108.0*geom_scale))
            est_h = max(60.0*geom_scale, min(160.0*geom_scale, 104.0*geom_scale))
            cand.append((score, {
                'cx': body_cx, 'cy': cy+0.12*bh,
                'w': est_w, 'h': est_h,
                'x': body_cx-est_w/2, 'y': cy-est_h/2,
                'detected': True, 'geom_scale': geom_scale,
                'red_pixels': rn, 'yellow_pixels': yn, 'white_pixels': wn
            }))

        self.last_candidates = len(cand)

        if cand:
            # Identity-first candidate selection. If the real chicken is still
            # visible near the last confirmed location, prefer that candidate
            # over a brighter distant colour blob. A genuine lane jump removes
            # the near candidate and the far candidate is then confirmed across
            # multiple frames by _confirm_candidate().
            chosen = None
            if self.last is not None and self.lane_spacing_hint is not None:
                near_r=max(45.0*geom_scale, self.prefer_near_fraction*self.lane_spacing_hint)
                near=[z for z in cand if abs(float(z[1]['cx'])-float(self.last['cx'])) <= near_r]
                if near:
                    chosen=max(near,key=lambda z:z[0])
            if chosen is None:
                chosen=max(cand,key=lambda z:z[0])
            score, best = chosen
            best['confidence'] = float(np.clip((score-2500.0)/15000.0, .08, .99))
            self.missing = 0
            return self._confirm_candidate(best)

        self.missing += 1
        if self.last is not None and self.missing <= self.max_missing:
            held = dict(self.last)
            held['detected'] = False
            held['confidence'] = max(
                0.0,
                float(held.get('confidence', .5)) *
                (1.0 - self.missing/(self.max_missing+1))
            )
            return held
        return None

