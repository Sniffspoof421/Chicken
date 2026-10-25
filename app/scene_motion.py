import cv2
import numpy as np
from collections import deque


class ScenePanDetector:
    """Detect horizontal viewport/camera movement from the road grid.

    The game view can be dragged left/right while the chicken and road move
    together on screen. Those movements are NOT chicken jumps and must not be
    learned as crashes/successes.

    This detector uses a cheap 1-D profile of bright, low-saturation road
    markings. It runs on a small resized road band and estimates the common
    horizontal translation between consecutive frames.
    """

    def __init__(self,cfg):
        self.profile_width=int(cfg.get('scene_profile_width',320))
        self.top=float(cfg.get('scene_profile_top_ratio',.06))
        self.bottom=float(cfg.get('scene_profile_bottom_ratio',.44))
        self.min_shift_px=float(cfg.get('scene_pan_min_shift_px',18.0))
        self.min_score=float(cfg.get('scene_pan_min_score',.72))
        self.max_shift_fraction=float(cfg.get('scene_pan_max_shift_fraction',.35))
        self.phase_min_response=float(cfg.get('scene_phase_min_response',.10))
        self.hold_seconds=float(cfg.get('scene_pan_hold_seconds',.55))
        self.prev=None
        self.prev_img=None
        self.cumulative_shift=0.0
        self.last_pan=-1e9
        self.last_shift=0.0
        self.last_score=0.0
        self.pan_count=0

    def _profile(self,frame):
        h,w=frame.shape[:2]
        y1=max(0,min(h-1,int(h*self.top)))
        y2=max(y1+20,min(h,int(h*self.bottom)))
        roi=frame[y1:y2]
        if roi.size==0:
            return None
        new_h=max(30,int(roi.shape[0]*self.profile_width/max(1,roi.shape[1])))
        small=cv2.resize(roi,(self.profile_width,new_h),interpolation=cv2.INTER_AREA)
        hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
        # Road divider paint is bright with low saturation.
        mask=((hsv[:,:,1] < 70) & (hsv[:,:,2] > 165)).astype(np.float32)
        prof=mask.sum(axis=0)
        prof-=float(prof.mean())
        return prof

    def _scene_image(self, frame):
        """Low-resolution road image used for large-pan phase correlation.

        The 1-D divider profile is periodic and can alias by one lane spacing.
        A second, non-periodic grayscale/edge image catches larger manual drags
        and scene translations that the divider-only search can miss.
        """
        h,w=frame.shape[:2]
        y1=max(0,min(h-1,int(h*self.top)))
        y2=max(y1+30,min(h,int(h*min(.80,max(self.bottom,.62)))))
        roi=frame[y1:y2]
        if roi.size==0:
            return None
        new_h=max(48,int(roi.shape[0]*self.profile_width/max(1,roi.shape[1])))
        small=cv2.resize(roi,(self.profile_width,new_h),interpolation=cv2.INTER_AREA)
        gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY).astype(np.float32)
        gray=cv2.GaussianBlur(gray,(5,5),0)
        # emphasize structure (lane markings, sidewalk, obstacles), while
        # de-emphasizing uniform asphalt and vertically moving traffic.
        gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)
        feat=0.55*gray + 0.45*np.abs(gx)
        feat-=float(feat.mean())
        return feat

    def update(self,frame,now):
        p=self._profile(frame)
        img=self._scene_image(frame)
        if p is None:
            return {'pan_active':False,'stable':False,'shift_px':0.0,'score':0.0,
                    'cumulative_shift_px':float(self.cumulative_shift)}

        shift_px=0.0
        score=0.0
        phase_score=0.0
        active=False
        if self.prev is not None and len(self.prev)==len(p):
            maxs=max(3,int(len(p)*self.max_shift_fraction))
            corr=np.correlate(p,self.prev,mode='full')
            center=len(p)-1
            sub=corr[center-maxs:center+maxs+1]
            j=int(np.argmax(sub))
            shift_small=j-maxs
            denom=float(np.linalg.norm(p)*np.linalg.norm(self.prev)+1e-9)
            score=float(sub[j]/denom)
            profile_shift=float(shift_small)*(float(frame.shape[1])/float(len(p)))
            shift_px=profile_shift

            # Large-drag fallback. The divider profile can report ~0 when a
            # drag is close to an integer lane spacing because the grid repeats.
            if (
                img is not None and self.prev_img is not None
                and img.shape == self.prev_img.shape
            ):
                try:
                    (dx_small,_),phase_score=cv2.phaseCorrelate(self.prev_img,img)
                    phase_shift=float(dx_small)*(float(frame.shape[1])/float(img.shape[1]))
                    # Prefer phase correlation when it finds a materially larger
                    # common horizontal translation with usable response.
                    if (
                        float(phase_score) >= self.phase_min_response
                        and abs(phase_shift) >= max(self.min_shift_px,abs(profile_shift)+4.0)
                    ):
                        shift_px=phase_shift
                        score=max(score,float(phase_score))
                except Exception:
                    phase_score=0.0

            active=bool(
                abs(shift_px) >= self.min_shift_px
                and score >= min(self.min_score, max(.45,self.phase_min_response))
            )
            if active:
                self.last_pan=float(now)
                self.pan_count+=1
                self.cumulative_shift += float(shift_px)

        self.prev=p
        self.prev_img=None if img is None else img.copy()
        self.last_shift=float(shift_px)
        self.last_score=float(score)
        stable=bool(float(now)-self.last_pan >= self.hold_seconds)
        return {
            'pan_active':active,
            'stable':stable,
            'shift_px':float(shift_px),
            'score':float(score),
            'phase_score':float(phase_score),
            'hold_remaining':max(0.0,self.hold_seconds-(float(now)-self.last_pan)),
            'pan_count':int(self.pan_count),
            'cumulative_shift_px':float(self.cumulative_shift),
        }


class ProgressScrollGate:
    """Cluster normal game auto-scrolls and shorten only their settle penalty.

    Chicken Road automatically discards completed road after progress.  The
    raw pan detector intentionally remains conservative and reports the whole
    translation, but using its full hold/re-warm for every auto-scroll starves
    late-game GREEN opportunities.  This helper never allows GREEN while the
    image is actively moving.  It only treats the short post-pan tail as
    stable sooner when auto-scroll handling is enabled.
    """

    def __init__(self, cfg):
        self.enabled = bool(cfg.get('game_auto_scroll_enabled', True))
        self.quiet_seconds = float(cfg.get('progress_scroll_quiet_seconds', .22))
        self.context_seconds = float(cfg.get('progress_scroll_context_seconds', .90))
        self.last_pan = -1e9
        self.last_cluster_pan = -1e9
        self.count = 0

    def update(self, scene, now):
        now = float(now)
        active = bool(scene.get('pan_active', False))
        if self.enabled and active:
            if now - self.last_cluster_pan > self.context_seconds:
                self.count += 1
            self.last_pan = now
            self.last_cluster_pan = now

        age = max(0.0, now - self.last_pan)
        in_context = bool(self.enabled and age <= self.context_seconds)
        settling = bool(in_context and not active and age < self.quiet_seconds)
        # Active motion is always unsafe.  Once a game-scroll has been quiet for
        # a short interval, ignore only the raw detector's longer hold tail.
        effective_stable = bool(
            scene.get('stable', True)
            or (in_context and not active and age >= self.quiet_seconds)
        )
        return {
            'progress_scroll_active': bool(self.enabled and active),
            'progress_scroll_settling': settling,
            'progress_scroll_context': in_context,
            'progress_scroll_age': age if in_context else 0.0,
            'progress_scroll_count': int(self.count),
            'effective_stable': effective_stable,
        }


class FullscreenProgressReframeGate:
    """Detect Chicken Road's deterministic 3-lane fullscreen reframe.

    V5.3.8 uses a RECENT PEAK, not just the immediately previous frame.
    Low processing FPS can observe the game cut as 1070 -> 700 -> 190; the old
    prev-frame detector saw only 700 -> 190 (~1.2 lanes) and missed it. A short
    recent-peak window preserves the real third-lane origin without confusing a
    normal one-lane death/reset.

    The gate also exposes ``classify_crash_event`` as a last-resort safeguard:
    if CrashDetector confirms a two-lane progress reset before the visual gate
    fires, main.py converts that event into a progress reframe before any crash
    or GREEN-failure learning occurs.
    """

    def __init__(self, cfg):
        self.enabled = bool(cfg.get('fullscreen_progress_reframe_mode', True))
        self.min_shift_lanes = float(cfg.get('fullscreen_reframe_min_shift_lanes', 1.55))
        self.max_shift_lanes = float(cfg.get('fullscreen_reframe_max_shift_lanes', 2.45))
        self.max_first_lane_x_ratio = float(cfg.get('fullscreen_reframe_first_lane_max_x_ratio', .18))
        self.cooldown_seconds = float(cfg.get('fullscreen_reframe_cooldown_seconds', 1.0))
        self.settle_seconds = float(cfg.get('fullscreen_reframe_settle_seconds', .24))
        self.peak_window_seconds = float(cfg.get('fullscreen_reframe_peak_window_seconds', 1.60))
        self.last_x = None
        self.last_event = -1e9
        self.settle_until = -1e9
        self.count = 0
        self.last_dx = 0.0
        self.last_shift_lanes = 0.0
        self.last_peak_x = 0.0
        self.last_source = ''
        self.history = deque(maxlen=24)

    def _trim_history(self, now):
        cutoff = float(now) - self.peak_window_seconds
        while self.history and float(self.history[0][0]) < cutoff:
            self.history.popleft()

    def _is_reframe_pair(self, peak_x, x, spacing, frame_width):
        sp=max(40.0,float(spacing or 0.0))
        fw=max(1.0,float(frame_width or 0.0))
        peak=float(peak_x); x=float(x)
        back=peak-x
        lanes=back/sp
        at_first=bool(x <= fw*self.max_first_lane_x_ratio)
        ok=bool(
            at_first and back>0.0
            and self.min_shift_lanes <= lanes <= self.max_shift_lanes
        )
        return ok,back,lanes

    def _commit(self, peak_x, x, spacing, now, source):
        now=float(now)
        sp=max(40.0,float(spacing or 0.0))
        self.count += 1
        self.last_event = now
        self.settle_until = now + self.settle_seconds
        self.last_peak_x = float(peak_x)
        self.last_dx = float(x)-float(peak_x)
        self.last_shift_lanes = (float(peak_x)-float(x))/sp
        self.last_source = str(source)
        self.history.clear()
        self.history.append((now,float(x)))
        self.last_x=float(x)
        return {
            'detected': True,
            'active': True,
            'count': int(self.count),
            'dx': float(self.last_dx),
            'shift_lanes': float(self.last_shift_lanes),
            'age': 0.0,
            'peak_x': float(self.last_peak_x),
            'source': self.last_source,
        }

    def update(self, chicken, spacing, frame_width, now):
        now=float(now)
        out={
            'detected':False,
            'active':bool(now < self.settle_until),
            'count':int(self.count),
            'dx':0.0,
            'shift_lanes':0.0,
            'age':max(0.0,now-self.last_event) if self.last_event>-1e8 else 0.0,
            'peak_x':float(self.last_peak_x),
            'source':self.last_source,
        }
        if not self.enabled or chicken is None:
            return out
        try:
            x=float(chicken.get('cx',0.0))
            sp=max(40.0,float(spacing or 0.0))
            fw=max(1.0,float(frame_width or 0.0))
        except Exception:
            return out
        if sp<=40.0 or fw<=1.0:
            self.last_x=x
            return out

        self._trim_history(now)
        # Peak is taken from the short PRE-CURRENT history so an intermediate
        # frame cannot erase the third-lane origin.
        peak=max([v for _,v in self.history], default=(self.last_x if self.last_x is not None else x))
        self.history.append((now,x))
        self.last_x=x

        if now-self.last_event < self.cooldown_seconds:
            return out

        ok,_,_=self._is_reframe_pair(peak,x,sp,fw)
        if not ok:
            return out
        return self._commit(peak,x,sp,now,'recent_peak')

    def classify_crash_event(self, crash_event, spacing, frame_width, now):
        """Recognize a missed fullscreen cut before crash learning.

        CrashDetector stores run-start/max/reset geometry. A two-lane progress
        reset landing in the first-lane region is the same deterministic game
        cut and must be converted to progress, not learned as a death.
        """
        if not self.enabled or not crash_event:
            return {'detected':False}
        now=float(now)
        if now-self.last_event < self.cooldown_seconds:
            return {'detected':False}
        try:
            peak=float(crash_event.get('max_x'))
            x=float(crash_event.get('reset_x'))
            sp=max(40.0,float(spacing or 0.0))
            fw=max(1.0,float(frame_width or 0.0))
        except Exception:
            return {'detected':False}
        ok,_,_=self._is_reframe_pair(peak,x,sp,fw)
        if not ok:
            return {'detected':False}
        return self._commit(peak,x,sp,now,'crash_geometry')

    def status(self, now):
        now=float(now)
        peak_age=0.0
        if self.history:
            try:
                peak_val=max(v for _,v in self.history)
                peak_ts=max(t for t,v in self.history if v==peak_val)
                peak_age=max(0.0,now-float(peak_ts))
            except Exception:
                peak_age=0.0
        return {
            'detected':False,
            'active':bool(now < self.settle_until),
            'count':int(self.count),
            'dx':float(self.last_dx),
            'shift_lanes':float(self.last_shift_lanes),
            'age':max(0.0,now-self.last_event) if self.last_event>-1e8 else 0.0,
            'peak_x':float(self.last_peak_x),
            'peak_age':float(peak_age),
            'source':self.last_source,
        }

