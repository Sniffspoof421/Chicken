import numpy as np, cv2, time
from app.scene_motion import ScenePanDetector
from app.chicken import ChickenDetector
from app.target_lane import StableNextLane
from app.motion import MotionEngine


def synthetic_scene(w=1280,h=624):
    im=np.zeros((h,w,3),np.uint8)+105
    # road divider pattern
    for x in range(220,1200,220):
        cv2.line(im,(x,30),(x,440),(235,235,235),5)
    # non-periodic static context so large shift is not aliased
    cv2.rectangle(im,(12,90),(105,420),(35,75,35),-1)
    cv2.rectangle(im,(960,70),(1010,180),(150,150,150),-1)
    cv2.circle(im,(760,140),34,(210,210,210),-1)
    return im


def translate(im,dx):
    M=np.float32([[1,0,dx],[0,1,0]])
    return cv2.warpAffine(im,M,(im.shape[1],im.shape[0]),borderValue=(105,105,105))


def test_large_pan_detection():
    cfg={
        'scene_profile_width':320,
        'scene_profile_top_ratio':.06,
        'scene_profile_bottom_ratio':.44,
        'scene_pan_min_shift_px':18,
        'scene_pan_min_score':.72,
        'scene_pan_max_shift_fraction':.35,
        'scene_phase_min_response':.10,
        'scene_pan_hold_seconds':.45,
    }
    d=ScenePanDetector(cfg)
    a=synthetic_scene(); b=translate(a,310)
    d.update(a,0.0)
    r=d.update(b,.1)
    assert r['pan_active'], r
    assert abs(r['shift_px']-310) < 45, r


def test_coordinate_rebase():
    c=ChickenDetector({})
    c.last={'cx':200.,'cy':300.,'x':150.,'y':250.,'w':100.,'h':100.}
    c.raw_last=dict(c.last)
    c.rebase_viewport(180)
    assert abs(c.last['cx']-380)<1e-6
    assert abs(c.last['x']-330)<1e-6

    t=StableNextLane()
    t.lane_id=2; t.lane_x=620.
    t.rebase_viewport(-140)
    assert abs(t.lane_x-480)<1e-6

    m=MotionEngine({'background_warmup_frames':1})
    from collections import deque
    m.tracks[1]={'cx':500.,'start_cx':480.,'history':deque([(1.,500.,100.),(2.,505.,120.)],maxlen=30)}
    m.rebase_viewport(-90)
    assert abs(m.tracks[1]['cx']-410)<1e-6
    assert abs(m.tracks[1]['history'][-1][1]-415)<1e-6

if __name__=='__main__':
    test_large_pan_detection()
    test_coordinate_rebase()
    print('V5.0.2 viewport rebase tests PASS')
