
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.target_lane import StableNextLane

l=StableNextLane(arrival_fraction=.22,switch_min_seconds=.45)
x=l.update([(1,400.0)],190.0,200.0,0.0)
assert x==(1,400.0),x
x=l.update([(0,200.0)],192.0,200.0,1.0)
assert x==(1,400.0),x
x=l.update([(2,600.0)],220.0,200.0,2.0)
assert x==(1,400.0),x
x=l.update([(2,600.0)],370.0,200.0,3.0)
assert x==(2,600.0),x
assert l.switches==1,l.switches
print("V4.4.0 lane hysteresis PASSED")
