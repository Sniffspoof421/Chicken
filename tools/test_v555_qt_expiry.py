"""Exercise the actual App callback with a Qt timer, without screen capture."""
import ast, math, time, sys
from pathlib import Path
from types import SimpleNamespace, MethodType
from PySide6.QtCore import QCoreApplication,QTimer,Qt
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.display_lease import expire_state
from app.outcome import GreenJumpOutcomeTracker
source=ast.parse((ROOT/'main.py').read_text())
app_class=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='App')
callback=next(n for n in app_class.body if isinstance(n,ast.FunctionDef) and n.name=='_expire_green_display')
namespace=dict(time=time,math=math,expire_state=expire_state)
exec(compile(ast.Module(body=[callback],type_ignores=[]),'<actual App callback>','exec'),namespace)
qt=QCoreApplication.instance() or QCoreApplication([])
o=GreenJumpOutcomeTracker({})
start=time.time();deadline=start+.08
o.current_signal=dict(start_ts=start,end_ts=start,duration=0.)
updates=[]
fake=SimpleNamespace(last=dict(indicator_state='CLEAR',green_display_deadline=deadline),
 outcome=o,indicator=SimpleNamespace(clear_hold_until=100.),
 ui=SimpleNamespace(update=lambda:updates.append(time.time())))
fake._expire_green_display=MethodType(namespace['_expire_green_display'],fake)
fake.green_expiry_timer=QTimer()
fake.green_expiry_timer.setSingleShot(True)
fake.green_expiry_timer.setTimerType(Qt.TimerType.PreciseTimer)
fake.green_expiry_timer.timeout.connect(fake._expire_green_display)
fake.green_expiry_timer.start(80)
QTimer.singleShot(180,qt.quit)
qt.exec()
assert updates and updates[0]>=deadline
assert fake.last['indicator_state']=='ETA HOLD'
assert fake.indicator.clear_hold_until==0.
assert o.pending_signal['end_ts']==deadline and o.current_signal is None
print('PASS actual Qt expiry callback: repaint, hold release, exact signal end timestamp')
