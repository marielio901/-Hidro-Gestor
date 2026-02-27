from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.simulator import generate_synthetic_data


if __name__ == "__main__":
    summary = generate_synthetic_data(months=6, seed=20250225, reset_db=True)
    print("Dados gerados:")
    for k, v in summary.items():
        print(f"- {k}: {v}")
