
import sys,cv2,numpy as np
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.scene_motion import ScenePanDetector

d=ScenePanDetector({
 'scene_profile_width':320,'scene_profile_top_ratio':.06,
 'scene_profile_bottom_ratio':.44,'scene_pan_min_shift_px':18,
 'scene_pan_min_score':.72,'scene_pan_max_shift_fraction':.08,
 'scene_pan_hold_seconds':.55,
})

def scene(dx=0):
    f=np.zeros((600,1280,3),np.uint8)+105
    for x in [200,420,640,860,1080]:
        xx=x+dx
        if 0<=xx<1280:
            for y in range(40,300,90):
                cv2.line(f,(xx,y),(xx,y+42),(235,235,235),6)
    return f

a=d.update(scene(0),0.0)
b=d.update(scene(0),0.1)
c=d.update(scene(55),0.2)
assert not b['pan_active'],b
assert c['pan_active'],c
assert abs(c['shift_px'])>=18,c
print("V4.3.8 scene pan detector PASSED",c)
