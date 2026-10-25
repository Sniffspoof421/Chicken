from pathlib import Path
import traceback

try:
    from main import main
    main()
except Exception:
    d=Path(__file__).resolve().parent
    (d/'runtime_v5517_error.log').write_text(traceback.format_exc(),encoding='utf-8')
    raise
