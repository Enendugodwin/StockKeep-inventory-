"""Development launcher (source checkout).

Run:  .venv\\Scripts\\python.exe run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stockkeep.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
