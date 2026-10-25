import mss
import numpy as np
import cv2

class ScreenCapture:
    def __init__(self, cfg):
        self.sct = mss.mss()
        self.monitor_index = int(cfg.get("monitor", 1))
        self.region = cfg.get("region")

    def grab(self):
        if self.region:
            mon = self.region
        else:
            monitors = self.sct.monitors
            if self.monitor_index >= len(monitors):
                self.monitor_index = 1
            mon = monitors[self.monitor_index]

        img = np.array(self.sct.grab(mon))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def close(self):
        self.sct.close()
