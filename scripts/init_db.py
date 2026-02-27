from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.db import init_db


if __name__ == "__main__":
    path = init_db(drop_existing=False)
    print(f"Banco inicializado em: {path}")
