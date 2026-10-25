
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.crash import CrashDetector
from app.outcome import GreenJumpOutcomeTracker
c=CrashDetector({'reset_back_px':180,'min_progress_px':140})
c.update({'cx':100,'detected':True},now=1)
c.update({'cx':400,'detected':True},now=2)
c.rebase_viewport({'cx':50,'detected':True},now=3)
assert c.update({'cx':52,'detected':True},now=3.2) is None
o=GreenJumpOutcomeTracker({})
o.current_signal={'signal_id':1}
assert o.invalidate_viewport({'cx':50}) is True
assert o.failures==0
print("V4.3.8 viewport rebase/invalidation PASSED")
