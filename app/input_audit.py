"""Windows jump-control edge timestamps; diagnostic only, never injects input."""
import json
import os
import threading
import time
import queue

CONTROLS = {1:'left_mouse', 32:'space', 38:'up', 39:'right'}

def input_record(control, wall, monotonic, state, cursor=None, foreground=None):
    deadline=state.get('green_display_deadline')
    return dict(kind='input_observed', control=control, timestamp=wall,
                monotonic=monotonic, cursor=cursor, foreground=foreground,
                cue_state=state.get('indicator_state'),
                cue_within_deadline=bool(state.get('indicator_state')=='CLEAR'
                    and deadline is not None and wall<float(deadline)),
                green_display_deadline=deadline,
                cue_foreground=state.get('input_foreground'),
                signal_id=state.get('visible_green_signal_id'),
                target_lane_x=state.get('target_lane_x'),
                target_lane_switches=state.get('target_lane_switches'),
                chicken_x=state.get('chicken_x'), chicken_y=state.get('chicken_y'))

class InputAudit:
    def __init__(self, path, state):
        self.path=path; self.state=state; self.stop_event=threading.Event()
        self.thread=None; self.error=None
        self.events=queue.Queue(maxsize=256)
        if os.name=='nt':
            self.thread=threading.Thread(target=self._run,daemon=True,name='jump-input-audit')
            self.thread.start()

    def _run(self):
        try:
            import ctypes
            from ctypes import wintypes
            user=ctypes.windll.user32
            user.GetAsyncKeyState.argtypes=[ctypes.c_int]
            user.GetAsyncKeyState.restype=ctypes.c_short
            user.GetForegroundWindow.restype=wintypes.HWND
            user.GetCursorPos.argtypes=[ctypes.POINTER(wintypes.POINT)]
            # A held key at startup is not a new input edge.
            previous={k:bool(user.GetAsyncKeyState(k)&0x8000) for k in CONTROLS}
            with self.path.open('a',encoding='utf-8') as log:
                log.write(json.dumps(dict(kind='input_audit_started',timestamp=time.time(),
                    controls=list(CONTROLS.values()),poll_seconds=.01))+'\n');log.flush()
                while not self.stop_event.wait(.01):
                    for key,name in CONTROLS.items():
                        down=bool(user.GetAsyncKeyState(key)&0x8000)
                        if down and not previous[key]:
                            wall=time.time();mono=time.perf_counter();point=wintypes.POINT()
                            cursor=[point.x,point.y] if user.GetCursorPos(ctypes.byref(point)) else None
                            record=input_record(name,wall,mono,self.state(),cursor,
                                                int(user.GetForegroundWindow() or 0))
                            log.write(json.dumps(record)+'\n');log.flush()
                            try:self.events.put_nowait(record)
                            except queue.Full:self.error='input queue overflow'
                        previous[key]=down
        except Exception as exc:
            self.error=f'{type(exc).__name__}: {exc}'

    @staticmethod
    def foreground():
        if os.name!='nt':return None
        try:
            import ctypes
            from ctypes import wintypes
            f=ctypes.windll.user32.GetForegroundWindow
            f.restype=wintypes.HWND
            return int(f() or 0)
        except Exception:return None

    def drain(self):
        records=[]
        while True:
            try:records.append(self.events.get_nowait())
            except queue.Empty:return records

    def close(self):
        self.stop_event.set()
        if self.thread is not None:self.thread.join(timeout=1.)
