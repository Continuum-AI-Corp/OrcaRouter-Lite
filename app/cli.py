"""Console entry point for `orcarouter-lite` (and `python -m app`).

`scripts/start.py`, the Docker CMD and the pip-installed console script all
funnel through here, so a checkout, a container and `pip install
orcarouter-lite` boot the server the same way.
"""

from __future__ import annotations

import argparse
import os


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("orcarouter-lite")
    except PackageNotFoundError:  # running straight from a checkout
        return "(source checkout)"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orcarouter-lite",
        description="Self-hosted LLM router with a managed safety net — OpenAI-compatible, BYOK.",
    )
    p.add_argument(
        "--host",
        default=os.environ.get("HOST", "0.0.0.0"),
        help="bind address (env: HOST, default: 0.0.0.0)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="bind port (env: PORT, default: 8000)",
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "info"),
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="uvicorn log level (env: LOG_LEVEL, default: info)",
    )
    p.add_argument(
        "--reload",
        action="store_true",
        help="restart on code changes (development only)",
    )
    p.add_argument("--version", action="version", version=f"orcarouter-lite {_version()}")
    return p


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    args = _build_parser().parse_args(argv)
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
        access_log=True,
    )
