"""Production-style boot — uvicorn with sane defaults.

Thin wrapper so `python scripts/start.py` (Docker CMD, Railway / Fly start
command, the benchmark workflow) keeps working. The logic lives in `app.cli`
because `scripts/` is not part of the wheel — only `app/` and `packages/` are.
"""

import sys
from pathlib import Path

# Docker and CI set PYTHONPATH explicitly, but a bare `python scripts/start.py`
# only puts `scripts/` on sys.path — add the repo root so `app` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
