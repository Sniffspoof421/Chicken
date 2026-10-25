
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.target_lane import StableNextLane

# Old V4.4.0 hysteresis case must still work.
l=StableNextLane(arrival_fraction=.22,switch_min_seconds=.35,
                 min_ahead_fraction=.10,max_ahead_fraction=1.55,
                 reanchor_fraction=.18)
assert l.update([(1,400.0)],190.0,200.0,0.0)==(1,400.0)
assert l.update([(0,200.0)],192.0,200.0,1.0)==(1,400.0)
assert l.update([(2,600.0)],220.0,200.0,2.0)==(1,400.0)
assert l.update([(2,600.0)],370.0,200.0,3.0)==(2,600.0)

# New critical case: viewport auto-scroll/reset makes old target many lane
# spacings ahead. Reacquire the immediate geometric next lane immediately.
l2=StableNextLane(max_ahead_fraction=1.55)
assert l2.update([(5,2326.0)],1875.0,450.0,0.0)==(5,2326.0)
x=l2.update([(1,550.0)],92.0,450.0,2.0)
assert x==(1,550.0),x
g=l2.geometry(92.0,450.0)
assert g['ok'] and .9 < g['ratio'] < 1.2,g

# Silent same-ID center shift should reanchor if geometry stays plausible.
l3=StableNextLane(reanchor_fraction=.18)
assert l3.update([(1,650.0)],190.0,450.0,0.0)==(1,650.0)
x=l3.update([(1,720.0)],260.0,450.0,1.0)
# 70px < .18*450 => stable hold.
assert x==(1,650.0),x
x=l3.update([(1,760.0)],300.0,450.0,2.0)
assert x==(1,760.0),x
print("V4.4.1 immediate-target geometry PASSED")
