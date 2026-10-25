from collections import deque
import cv2
import numpy as np


class LaneMapper:
    """Detect road divider grid and derive lane centres.

    V4.3.3 makes every geometric threshold resolution-aware.  Older builds
    tuned divider spacing around a 1280px capture; at ~2560px the real divider
    spacing doubles and the mapper never became ready, leaving risk at the
    35% fallback forever.
    """
    def __init__(self,cfg):
        self.samples=deque(maxlen=int(cfg.get('sample_history',8000)))
        self.min_motion=float(cfg.get('min_vertical_speed',18))
        self.min_vertical_ratio=float(cfg.get('min_vertical_ratio',1.10))
        self.min_ahead_px=float(cfg.get('min_ahead_px',28))
        self.marking_top=float(cfg.get('marking_top_ratio',.04))
        self.marking_bottom=float(cfg.get('marking_bottom_ratio',.73))

        self.reference_width=float(cfg.get('reference_width_px',1280.0))
        self.reference_height=float(cfg.get('reference_height_px',624.0))
        self.divider_min_spacing_base=float(cfg.get('divider_min_spacing_px',150))
        self.divider_max_spacing_base=float(cfg.get('divider_max_spacing_px',250))
        self.divider_expected_spacing_base=float(cfg.get('divider_expected_spacing_px',220))
        self.peak_separation_base=float(cfg.get('peak_separation_px',18))
        self.grid_edge_margin_base=float(cfg.get('grid_edge_margin_px',18.0))

        self.boundaries=[]
        self.centers=[]
        self.source='learning'
        self.spacing=None
        self.total_level_lanes=int(cfg.get('total_level_lanes',22))
        self.frame_width=None
        self.frame_height=None
        self.frame_no=0
        self.startup_refresh_frames=int(cfg.get('marking_startup_refresh_frames',2))
        self.locked_refresh_frames=int(cfg.get('marking_locked_refresh_frames',10))
        self.traffic_fallback_min_samples=int(cfg.get('traffic_fallback_min_samples',90))
        self.traffic_fallback_min_centers=int(cfg.get('traffic_fallback_min_centers',3))

        # V5.3.3: lane-grid phase is anchored to the confirmed chicken.  The
        # road is periodic, so a white-object chain can occasionally lock half
        # a lane out of phase even though spacing is correct.  Persist the small
        # phase correction so later marking refreshes do not immediately pull
        # the grid back onto the wrong periodic chain.
        self.phase_bias=0.0
        self.phase_realigns=0
        self.last_phase_shift=0.0
        self.last_phase_error=0.0

    def _scale(self,w,h=None):
        sx=float(w)/max(1.0,self.reference_width)
        sy=(float(h)/max(1.0,self.reference_height)) if h else sx
        geom=float(np.sqrt(max(.05,sx*sy)))
        return sx,sy,geom

    def _spacing_limits(self,w):
        sx=float(w)/max(1.0,self.reference_width)
        return (
            self.divider_min_spacing_base*sx,
            self.divider_max_spacing_base*sx,
            self.divider_expected_spacing_base*sx,
        )

    def _longest_periodic_chain(self,xs,w):
        if not xs:return []
        min_sp,max_sp,target=self._spacing_limits(w)
        best=[]
        for sx in xs:
            chain=[float(sx)]
            local_target=float(self.spacing or target)
            used={float(sx)}
            while True:
                opts=[float(x) for x in xs
                      if x not in used and min_sp <= float(x)-chain[-1] <= max_sp]
                if not opts:break
                nx=min(opts,key=lambda x:abs((x-chain[-1])-local_target))
                if len(chain)>=2:
                    prev=np.diff(chain+[nx])
                    local_target=float(np.median(prev))
                chain.append(nx); used.add(nx)
            if len(chain)>len(best):best=chain
            elif len(chain)==len(best) and len(chain)>=2:
                err=np.std(np.diff(chain))
                berr=np.std(np.diff(best)) if len(best)>=2 else 1e9
                if err<berr:best=chain
        return best

    def _expand_grid(self,best,sp,w):
        if not best:return best
        edge=self.grid_edge_margin_base*(float(w)/max(1.0,self.reference_width))
        best=[float(x) for x in best]

        left=best[0]
        # Add boundaries needed to define every visible centre on the left.
        while left-sp/2.0 > edge:
            left-=sp
            best.insert(0,float(left))

        right=best[-1]
        # One boundary is allowed to sit outside the visible frame if the lane
        # centre between it and the last visible divider is still on-screen.
        # This fixes the final right-hand lane when the chicken is far across.
        while right+sp/2.0 < float(w)-edge:
            right+=sp
            best.append(float(right))
        return best

    def _detect_markings(self,frame):
        h,w=frame.shape[:2]
        self.frame_width=w; self.frame_height=h
        sx,sy,geom=self._scale(w,h)
        roi=frame[int(h*self.marking_top):int(h*self.marking_bottom)]
        if roi.size==0:return []

        hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(
            hsv,
            np.array([0,0,145],np.uint8),
            np.array([179,110,255],np.uint8)
        )
        col=(mask>0).sum(axis=0).astype(float)
        k=max(5,int(round(7.0*sx)))
        if k%2==0:k+=1
        col=np.convolve(col,np.ones(k)/k,mode='same')

        # Do not let the bright sidewalk / browser-side UI dominate the white
        # threshold.  The divider grid is on the road to the right.
        road_x0=max(0,min(w-1,int(.20*w)))
        thr=max(20.0*sy,float(np.percentile(col[road_x0:],78)))

        margin=max(8,int(round(8*sx)))
        raw=[(col[x],x) for x in range(max(margin,road_x0),w-margin)
             if col[x]>=thr and col[x]>=col[x-1] and col[x]>=col[x+1]]
        peaks=[]
        min_peak_sep=max(12,int(round(self.peak_separation_base*sx)))
        for v,x in sorted(raw,reverse=True):
            if all(abs(x-px)>=min_peak_sep for _,px in peaks):
                peaks.append((float(v),int(x)))
        xs=sorted(x for _,x in peaks)

        best=self._longest_periodic_chain(xs,w)
        if len(best)<3:return []
        sp=float(np.median(np.diff(best)))
        min_sp,max_sp,_=self._spacing_limits(w)
        if not (min_sp<=sp<=max_sp):return []
        if len(best)>=4 and float(np.std(np.diff(best)))/max(1.0,sp)>.10:
            return []

        best=self._expand_grid(best,sp,w)
        return [float(x) for x in best],sp

    def _traffic_fallback(self):
        """Conservative lane-centre fallback from vertically moving traffic.

        Old LaneMapper collected samples but never actually converted them into
        centres.  This fallback only locks when >=3 periodic peaks agree.
        """
        if self.frame_width is None or len(self.samples)<self.traffic_fallback_min_samples:
            return False
        w=float(self.frame_width)
        sx=w/max(1.0,self.reference_width)
        vals=np.asarray(self.samples,dtype=float)
        # Browser/nav motion is concentrated at the far left; road traffic in
        # this game begins farther right. Keep a broad road-compatible region.
        vals=vals[(vals>=.10*w)&(vals<=1.02*w)]
        if len(vals)<self.traffic_fallback_min_samples:return False

        bin_w=max(12.0,18.0*sx)
        edges=np.arange(0,w+bin_w,bin_w)
        hist,_=np.histogram(vals,bins=edges)
        smooth=np.convolve(hist.astype(float),np.ones(5)/5,mode='same')
        centers=(edges[:-1]+edges[1:])/2.0
        peak_idx=[]
        min_count=max(3.0,float(np.percentile(smooth,75)))
        for i in range(1,len(smooth)-1):
            if smooth[i]>=min_count and smooth[i]>=smooth[i-1] and smooth[i]>=smooth[i+1]:
                peak_idx.append(i)
        cand=[float(centers[i]) for i in peak_idx]
        chain=self._longest_periodic_chain(cand,int(w))
        if len(chain)<self.traffic_fallback_min_centers:return False
        sp=float(np.median(np.diff(chain)))
        if float(np.std(np.diff(chain)))/max(1.0,sp)>.14:return False

        self.centers=[float(x) for x in chain]
        self.spacing=sp
        self.boundaries=[self.centers[0]-sp/2.0]+[x+sp/2.0 for x in self.centers]
        self.source='traffic'
        return True

    def update(self,tracks,frame_or_shape):
        frame=frame_or_shape if hasattr(frame_or_shape,'shape') else None
        self.frame_no+=1
        if frame is not None:
            h,w=frame.shape[:2]
            self.frame_width=w; self.frame_height=h
            interval=self.locked_refresh_frames if self.centers else self.startup_refresh_frames
            should_scan=(self.frame_no<=2 or self.frame_no%max(1,interval)==0)
            if should_scan:
                got=self._detect_markings(frame)
                if got:
                    b,sp=got
                    # V5.3.3: preserve chicken-derived lane phase across marking
                    # refreshes.  Spacing still comes from the markings; only the
                    # periodic phase is corrected.
                    if abs(float(self.phase_bias)) > 1e-6:
                        b=[float(x)+float(self.phase_bias) for x in b]
                    # At a resolution change, old spacing can legitimately
                    # change by ~2x. Compare normalized spacing, not raw pixels.
                    if self.spacing is None or abs(sp-self.spacing)/max(1.0,self.spacing)<.18:
                        self.spacing=sp if self.spacing is None else .85*self.spacing+.15*sp
                        if len(self.boundaries)==len(b):
                            self.boundaries=[.85*a+.15*x for a,x in zip(self.boundaries,b)]
                        else:
                            self.boundaries=list(b)
                        self.centers=[(a+b)/2.0 for a,b in zip(self.boundaries[:-1],self.boundaries[1:])]
                        # Keep only centres whose midpoint is visible.
                        self.centers=[x for x in self.centers if 0.0<=x<=float(w)]
                        self.source='markings'
                        return

        # Once locked, keep the stable grid. Traffic events still use it, but
        # the mapper itself doesn't need to relearn every frame.
        if self.centers:return

        for t in tracks:
            vy=float(t.get('vy',0.0)); vx=float(t.get('vx',0.0))
            if vy>=self.min_motion and abs(vy)>abs(vx)*self.min_vertical_ratio:
                self.samples.append(float(t.get('cx',0.0)))
        self._traffic_fallback()

    def rebase_viewport(self, dx):
        """Shift the locked screen-space lane grid with a camera drag."""
        dx=float(dx or 0.0)
        if abs(dx) < 1e-6:
            return
        if self.frame_width is None:
            self.boundaries=[float(x)+dx for x in self.boundaries]
            self.centers=[float(x)+dx for x in self.centers]
            return
        w=float(self.frame_width)
        self.boundaries=[float(x)+dx for x in self.boundaries]
        self.centers=[float(x)+dx for x in self.centers]
        # Keep a modest off-screen margin so the next marking refresh can
        # reconcile the grid without deleting the immediate target mid-drag.
        margin=float(self.spacing or 200.0)
        self.centers=[x for x in self.centers if -margin <= x <= w+margin]


    def chicken_phase_error(self, chicken_x):
        """Signed screen-X error from the nearest lane centre to the chicken.

        A correctly phased grid should put a stable/landed chicken close to a
        lane centre.  The caller is responsible for invoking this only when the
        chicken is freshly detected and horizontally stable; during an actual
        jump the chicken is expected to sit between centres temporarily.
        """
        if not self.centers or self.spacing is None:
            return None
        cx=float(chicken_x)
        arr=np.asarray(self.centers,dtype=float)
        i=int(np.argmin(np.abs(arr-cx)))
        return float(cx-arr[i])

    def align_phase_to_chicken(self, chicken_x, min_fraction=.14, max_fraction=.58):
        """Re-phase the road grid so a stable chicken sits on a lane centre.

        Returns a diagnostic dict.  This never changes lane spacing; it shifts
        the periodic grid by at most ``max_fraction`` of one spacing.  Large
        errors are rejected as likely bad chicken identity rather than silently
        moving the traffic model to a false object.
        """
        if not self.centers or self.spacing is None:
            return {'changed':False,'reason':'NO_GRID','shift':0.0,'error':None,'ratio':None}
        sp=max(40.0,float(self.spacing))
        err=self.chicken_phase_error(chicken_x)
        if err is None:
            return {'changed':False,'reason':'NO_GRID','shift':0.0,'error':None,'ratio':None}
        ratio=float(err)/sp
        self.last_phase_error=float(err)
        if abs(ratio) < float(min_fraction):
            self.last_phase_shift=0.0
            return {'changed':False,'reason':'ALIGNED','shift':0.0,'error':float(err),'ratio':float(ratio)}
        if abs(ratio) > float(max_fraction):
            self.last_phase_shift=0.0
            return {'changed':False,'reason':'ERROR_TOO_LARGE','shift':0.0,'error':float(err),'ratio':float(ratio)}

        shift=float(err)
        self.boundaries=[float(x)+shift for x in self.boundaries]
        self.centers=[float(x)+shift for x in self.centers]
        self.phase_bias=float(self.phase_bias)+shift
        # Only phase matters. Keep the persistent bias in a compact modulo-one-
        # lane representation so repeated viewport refreshes cannot accumulate a
        # whole-lane translation.
        half=.5*sp
        while self.phase_bias > half:
            self.phase_bias -= sp
        while self.phase_bias < -half:
            self.phase_bias += sp
        self.phase_realigns += 1
        self.last_phase_shift=shift
        self.last_phase_error=0.0
        return {
            'changed':True,'reason':'CHICKEN_PHASE_SYNC','shift':shift,
            'error':float(err),'ratio':float(ratio),
            'phase_bias':float(self.phase_bias),
            'realigns':int(self.phase_realigns),
        }

    def lane_for(self,x):
        if not self.centers:return -1
        return int(np.argmin(np.abs(np.asarray(self.centers)-float(x))))

    def _extend_centers_right(self,needed=1):
        if not self.centers or self.spacing is None or self.frame_width is None:return
        edge=self.grid_edge_margin_base*(float(self.frame_width)/max(1.0,self.reference_width))
        guard=0
        while guard<int(needed)+2:
            guard+=1
            nx=float(self.centers[-1])+float(self.spacing)
            if nx>=float(self.frame_width)-edge:break
            self.centers.append(nx)

    def next_lanes(self,chicken_x,count=1):
        count=int(count)
        scale=(float(self.frame_width)/max(1.0,self.reference_width)) if self.frame_width else 1.0
        ahead_px=self.min_ahead_px*scale
        ahead=[(i,float(x)) for i,x in enumerate(self.centers)
               if float(x)>float(chicken_x)+ahead_px]
        if len(ahead)<count:
            self._extend_centers_right(count-len(ahead))
            ahead=[(i,float(x)) for i,x in enumerate(self.centers)
                   if float(x)>float(chicken_x)+ahead_px]
        ahead.sort(key=lambda z:z[1])
        return ahead[:count]

    @property
    def ready(self):
        return len(self.centers)>=2
