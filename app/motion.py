import cv2
import numpy as np
import math
import time
from collections import OrderedDict, deque


class MotionEngine:
    """Adaptive foreground detector + persistent tracker.

    V2.1 uses an adaptive MOG2 background model instead of only comparing two
    consecutive frames.  This is much more tolerant of different vehicle
    speeds and brief pauses.  Speeds are measured in pixels/second.
    """

    def __init__(self, cfg):
        self.max_dist = float(cfg.get('max_distance_px', 140))
        self.max_missing = int(cfg.get('max_missing_frames', 15))
        self.min_area = float(cfg.get('min_blob_area', 45))
        self.max_area = float(cfg.get('max_blob_area', 50000))
        self.blob_reference_width = float(cfg.get('blob_reference_width_px', 1280.))
        self.last_effective_max_area = self.max_area
        self.alpha = float(cfg.get('velocity_smoothing', 0.42))
        self.min_width = int(cfg.get('min_blob_width', 7))
        self.min_height = int(cfg.get('min_blob_height', 4))
        self.warmup_frames = int(cfg.get('background_warmup_frames', 20))
        self.history_frames = int(cfg.get('background_history_frames', 240))
        self.var_threshold = float(cfg.get('background_var_threshold', 20))
        self.learning_rate = float(cfg.get('background_learning_rate', -1.0))
        self.merge_kernel = int(cfg.get('merge_kernel', 5))

        # V4.2: real traffic moves TOP -> BOTTOM in screen coordinates.
        # OpenCV Y increases downward, therefore real vehicle vy is positive.
        self.expected_vy_sign = 1
        self.max_backward_match_px = float(cfg.get('max_backward_match_px', 14.0))
        self.direction_lock_age = int(cfg.get('direction_lock_age', 4))
        self.min_positive_vy_px_s = float(cfg.get('min_positive_vy_px_s', 8.0))
        self.velocity_fit_points = int(cfg.get('velocity_fit_points', 7))
        self.direction_fit_min_seconds = float(
            cfg.get('direction_fit_min_seconds', .08)
        )
        self.direction_consistency_min = float(
            cfg.get('direction_consistency_min', .60)
        )
        self.max_lateral_match_px = float(
            cfg.get('max_lateral_match_px', 85.0)
        )
        self.roi_warmup_frames = int(cfg.get('roi_warmup_frames', 5))
        self.diff_threshold = int(cfg.get('frame_diff_threshold', 18))
        self.diff_dilate = int(cfg.get('frame_diff_dilate', 2))
        self.roi_key = None
        self.prev_gray = None

        self.bg = self._new_background()
        self.tracks = OrderedDict()
        self.next_id = 1
        self.last_ts = None
        self.frame_no = 0

        # Exposed diagnostics used by the compass.
        self.last_detection_count = 0
        self.last_foreground_ratio = 0.0
        self.last_mog_ratio = 0.0
        self.last_diff_ratio = 0.0
        self.last_mask = None

    def _new_background(self):
        return cv2.createBackgroundSubtractorMOG2(
            history=self.history_frames,
            varThreshold=self.var_threshold,
            detectShadows=False,
        )

    def force_reset(self, roi_key=None):
        if roi_key is not None:
            self.roi_key = roi_key
        self.bg = self._new_background()
        self.tracks.clear()
        self.frame_no = 0
        self.last_ts = None
        self.prev_gray = None
        self.last_mask = None
        self.last_detection_count = 0
        self.last_foreground_ratio = 1.0
        self.last_mog_ratio = 1.0
        self.last_diff_ratio = 1.0

    def rebase_viewport(self, dx):
        """Translate live track X positions after horizontal camera motion."""
        dx=float(dx or 0.0)
        if abs(dx) < 1e-6:
            return
        for tr in self.tracks.values():
            for k in ('cx','start_cx'):
                if k in tr:
                    tr[k]=float(tr[k])+dx
            hist=tr.get('history')
            if hist is not None:
                shifted=[]
                for ts,x,y in list(hist):
                    shifted.append((ts,float(x)+dx,y))
                hist.clear(); hist.extend(shifted)

    def _switch_roi(self, roi_key):
        if roi_key == self.roi_key:
            return
        self.force_reset(roi_key=roi_key)

    def _detections(self, frame, roi=None):
        fh_full, fw_full = frame.shape[:2]
        # Area is in squared pixels. A 2x capture has 4x vehicle area.
        # Keep the configured limit at reference resolution; scale only upward.
        area_scale = max(1., float(fw_full)/max(1., self.blob_reference_width))**2
        self.last_effective_max_area = self.max_area*area_scale
        if roi is None:
            x0,y0,x1,y1 = 0,0,fw_full,fh_full
        else:
            x0,y0,x1,y1 = [int(v) for v in roi]
            x0=max(0,min(fw_full-1,x0)); x1=max(x0+1,min(fw_full,x1))
            y0=max(0,min(fh_full-1,y0)); y1=max(y0+1,min(fh_full,y1))
        work = frame[y0:y1, x0:x1]

        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        mog_mask = self.bg.apply(gray, learningRate=self.learning_rate)

        # Independent temporal motion. This continues to react when MOG2 has
        # gradually absorbed repetitive traffic into its background model.
        if self.prev_gray is not None and self.prev_gray.shape == gray.shape:
            delta=cv2.absdiff(gray,self.prev_gray)
            _,diff_mask=cv2.threshold(
                delta,self.diff_threshold,255,cv2.THRESH_BINARY
            )
            diff_mask=cv2.morphologyEx(
                diff_mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8),iterations=1
            )
            if self.diff_dilate>0:
                diff_mask=cv2.dilate(
                    diff_mask,np.ones((3,3),np.uint8),
                    iterations=self.diff_dilate
                )
        else:
            diff_mask=np.zeros_like(mog_mask)

        self.prev_gray=gray.copy()
        self.frame_no += 1
        self.last_mog_ratio=float(np.count_nonzero(mog_mask))/float(mog_mask.size)
        self.last_diff_ratio=float(np.count_nonzero(diff_mask))/float(diff_mask.size)

        # Combined evidence: either detector may veto an allegedly clear lane.
        mask=cv2.bitwise_or(mog_mask,diff_mask)

        # Ignore detections while the new spatial background initializes.
        if self.frame_no <= self.warmup_frames:
            self.last_detection_count = 0
            self.last_foreground_ratio = float(np.count_nonzero(mask)) / float(mask.size)
            self.last_mask = {
                'mask': mask, 'mog_mask': mog_mask, 'diff_mask': diff_mask,
                'x0': x0, 'y0': y0,
                'full_h': fh_full, 'full_w': fw_full,
                'ready': False
            }
            return []

        # Remove isolated noise and join fragmented portions of the same car.
        k_open = np.ones((3, 3), np.uint8)
        k_merge = np.ones((self.merge_kernel, self.merge_kernel), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_open, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_merge, iterations=2)
        mask = cv2.dilate(mask, k_open, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        fh, fw = work.shape[:2]
        for c in contours:
            area = cv2.contourArea(c)
            if not self.min_area <= area <= self.last_effective_max_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if w < self.min_width or h < self.min_height:
                continue
            # Skip near-full-screen foreground blobs caused by scene changes.
            if w > fw * 0.80 or h > fh * 0.80:
                continue
            crop = work[max(0,y):min(fh,y+h), max(0,x):min(fw,x+w)]
            if crop.size:
                hh = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                mh, ms, mv = [float(v) for v in cv2.mean(hh)[:3]]
            else:
                mh = ms = mv = 0.0
            out.append({
                'cx': x0 + x + w / 2.0,
                'cy': y0 + y + h / 2.0,
                'w': float(w),
                'h': float(h),
                'area': float(area),
                'mean_h': mh, 'mean_s': ms, 'mean_v': mv,
            })

        self.last_detection_count = len(out)
        self.last_foreground_ratio = float(np.count_nonzero(mask)) / float(mask.size)
        self.last_mask = {
            'mask': mask, 'mog_mask': mog_mask, 'diff_mask': diff_mask,
            'x0': x0, 'y0': y0,
            'full_h': fh_full, 'full_w': fw_full,
            'ready': True
        }
        return out

    def update(self, frame, timestamp=None, roi=None, roi_key=None):
        self._switch_roi(roi_key)
        ts = float(timestamp or time.perf_counter())
        dt = max(0.008, min(0.25, ts - (self.last_ts or ts - 1 / 30)))
        self.last_ts = ts
        dets = self._detections(frame, roi=roi)
        used = set()

        # Associate detections with velocity-predicted track positions.
        for tid, tr in list(self.tracks.items()):
            observed_dt = max(.008, ts-float(tr.get('ts',ts-dt)))
            prediction_vy = max(0., float(tr.get('vy',0.)))
            hist = list(tr.get('history',()))
            if len(hist)>=2:
                a,b=hist[-2:]
                span=float(b[0])-float(a[0])
                dx=float(b[1])-float(a[1]); dy=float(b[2])-float(a[2])
                if (0<span<=.35 and dy>=max(12.,self.min_positive_vy_px_s*span)
                        and abs(dx)<=max(12.,.25*dy)
                        and not tr.get('direction_suspicious',False)):
                    prediction_vy=dy/span
            px = tr['cx'] + tr.get('vx', 0.0) * observed_dt
            # Traffic is one-way +Y. Never let a stale negative vy predict a
            # vehicle upward and pull its ID onto an unrelated blob.
            py = tr['cy'] + prediction_vy * observed_dt
            best = None
            best_d = 1e9

            # Larger objects get a slightly larger association radius.
            assoc_limit = self.max_dist + min(80.0, 0.35 * max(tr.get('w', 0), tr.get('h', 0)))
            for i, d in enumerate(dets):
                if i in used:
                    continue

                # Mature real traffic should not jump significantly upward
                # between frames. Reject backward associations that would
                # create false negative vy / ID swaps.
                dy_obs = float(d['cy']) - float(tr['cy'])
                dx_obs = float(d['cx']) - float(tr['cx'])
                if (
                    int(tr.get('age', 0)) >= self.direction_lock_age
                    and dy_obs < -self.max_backward_match_px
                ):
                    continue
                if (
                    bool(tr.get('direction_valid', False))
                    and abs(dx_obs) > self.max_lateral_match_px
                ):
                    continue

                dist = math.hypot(d['cx'] - px, d['cy'] - py)

                # Small upward jitter is allowed, but penalized so a forward
                # detection is preferred when two blobs compete for one ID.
                if dy_obs < 0:
                    dist += abs(dy_obs) * 1.6

                if dist < best_d and dist <= assoc_limit:
                    best_d = dist
                    best = (i, d)

            if best:
                i, d = best
                used.add(i)
                raw_vx = (d['cx'] - tr['cx']) / observed_dt
                raw_vy = (d['cy'] - tr['cy']) / observed_dt

                hist = tr.setdefault('history', deque(maxlen=30))
                hist.append((ts, d['cx'], d['cy']))

                # Robust direction evidence from a short fitted history.
                # V4.2.3 logs showed a blob moving y=664->750 while stored vy
                # remained negative. The old EMA was carrying stale negative
                # velocity through a new forward association.
                pts = list(hist)[-max(3, self.velocity_fit_points):]
                fit_vx = raw_vx
                fit_vy = raw_vy
                net_vy = raw_vy
                direction_consistency = 0.0
                hist_span = 0.0

                if len(pts) >= 3:
                    tt = np.asarray([p[0] for p in pts], dtype=float)
                    xx = np.asarray([p[1] for p in pts], dtype=float)
                    yy = np.asarray([p[2] for p in pts], dtype=float)
                    tt = tt - tt[0]
                    hist_span = float(tt[-1])
                    if hist_span >= self.direction_fit_min_seconds:
                        try:
                            fit_vx = float(np.polyfit(tt, xx, 1)[0])
                            fit_vy = float(np.polyfit(tt, yy, 1)[0])
                            net_vy = float((yy[-1] - yy[0]) / max(.001, hist_span))
                            dys = np.diff(yy)
                            direction_consistency = float(
                                np.mean(dys >= -self.max_backward_match_px * .35)
                            ) if len(dys) else 0.0
                        except Exception:
                            pass

                direction_valid = bool(
                    hist_span >= self.direction_fit_min_seconds
                    and fit_vy >= self.min_positive_vy_px_s
                    and net_vy >= self.min_positive_vy_px_s * .50
                    and direction_consistency >= self.direction_consistency_min
                )

                # If net displacement says the object is moving down but the
                # fitted/stored velocity disagrees, mark it suspicious. RiskEngine
                # will veto GREEN rather than pretending the lane is empty.
                direction_suspicious = bool(
                    hist_span >= self.direction_fit_min_seconds
                    and (
                        (net_vy >= self.min_positive_vy_px_s and fit_vy < 0.0)
                        or (
                            abs(net_vy) >= self.min_positive_vy_px_s
                            and direction_consistency < self.direction_consistency_min
                        )
                    )
                )

                vx = (1 - self.alpha) * float(tr.get('vx', fit_vx)) + self.alpha * fit_vx

                # One-way +Y traffic: never let an old negative EMA dominate.
                prev_vy = max(0.0, float(tr.get('vy', 0.0)))
                positive_estimates = [
                    v for v in (fit_vy, net_vy, raw_vy)
                    if np.isfinite(v) and v > 0.0
                ]
                robust_forward_vy = (
                    float(np.median(positive_estimates))
                    if positive_estimates else 0.0
                )
                vy = (1 - self.alpha) * prev_vy + self.alpha * robust_forward_vy
                if not direction_valid and robust_forward_vy < self.min_positive_vy_px_s:
                    vy = 0.0

                speed = math.hypot(vx, vy)
                accel = (speed - tr.get('speed', speed)) / observed_dt
                # Smooth appearance so one fragmented foreground frame does not
                # completely change the learned vehicle type.
                for ak in ('mean_h','mean_s','mean_v'):
                    if ak in d:
                        d[ak] = 0.72*float(tr.get(ak,d[ak])) + 0.28*float(d[ak])
                tr.update(d)
                tr.update(
                    vx=vx,
                    vy=vy,
                    fit_vy=float(fit_vy),
                    net_vy=float(net_vy),
                    direction_consistency=float(direction_consistency),
                    direction_valid=bool(direction_valid),
                    direction_suspicious=bool(direction_suspicious),
                    speed=speed,
                    accel=accel,
                    missing=0,
                    age=tr.get('age', 0) + 1,
                    matched_count=tr.get('matched_count', 1) + 1,
                    ts=ts,
                    matched=True,
                )
            else:
                tr['missing'] = tr.get('missing', 0) + 1
                tr['matched'] = False

        for i, d in enumerate(dets):
            if i in used:
                continue
            self.tracks[self.next_id] = {
                **d,
                'vx': 0.0,
                'vy': 0.0,
                'fit_vy': 0.0,
                'net_vy': 0.0,
                'direction_consistency': 0.0,
                'direction_valid': False,
                'direction_suspicious': False,
                'speed': 0.0,
                'accel': 0.0,
                'missing': 0,
                'age': 1,
                'matched_count': 1,
                'start_cx': float(d['cx']),
                'start_cy': float(d['cy']),
                'ts': ts,
                'matched': True,
                'history': deque([(ts, d['cx'], d['cy'])], maxlen=30),
            }
            self.next_id += 1

        for tid in [i for i, t in self.tracks.items() if t.get('missing', 0) > self.max_missing]:
            del self.tracks[tid]

        # A track is considered usable once it has survived at least two frames.
        return [
            {'id': tid, **{k: v for k, v in tr.items() if k != 'history'}}
            for tid, tr in self.tracks.items()
            if tr.get('missing', 0) == 0 and tr.get('age', 0) >= 2
        ]

    def prediction_tracks(self):
        """Separate veto-only snapshots; keep learning/detection outputs unchanged.

        History is necessary for the two-observation predictor. Missing tracks
        remain bounded by the tracker's existing expiry and ROI reset lifecycle.
        The predictor additionally expires them at their estimated rear exit.
        """
        return [dict(tr, id=tid, history=tuple(tr.get('history', ())))
                for tid, tr in self.tracks.items()]
