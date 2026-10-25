import sys,time,importlib.util
from pathlib import Path
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('tested_main',ROOT/'main.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
app=QApplication.instance() or QApplication([])
state=dict(indicator_state='HOLD',display_risk=50.)
w=m.Compass(lambda:state);w.show();app.processEvents()
state.update(indicator_state='CLEAR',visible_green_signal_id=7,green_display_deadline=time.time()+1.)
w.repaint()
assert [e['kind'] for e in w.presentation_events]==['green_painted']
w.repaint();assert len(w.presentation_events)==1
state['green_display_deadline']=time.time()-1
w.repaint()
assert w.presentation_events[-1]['kind']=='green_paint_ended'
# A cue already expired before painting must not be counted as painted.
state.update(visible_green_signal_id=8)
w.repaint();assert len(w.presentation_events)==2
w.close()
print('PASS actual Qt paint audit, dedup and expired-before-paint exclusion')
