"""Tripwires for the distribution artifacts.

`pip install orcarouter-lite` has to produce a server that boots *and* serves
the dashboard. Three pieces make that work, and none of them are touched by the
rest of the suite:

  * the `orcarouter-lite` console script -> `app.cli:main`
  * pyproject force-including the repo-root `design/` tree into `app/design/`
  * `app.main._find_design_dir()` preferring that installed location

CI's `package` job runs the real end-to-end check (build the wheel, install it
into a clean venv, boot it, curl `/`). These are the cheap unit-level guards so
a regression shows up in the normal test run instead of at release time.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_console_script_points_at_a_real_callable(pyproject: dict) -> None:
    assert pyproject["project"]["scripts"]["orcarouter-lite"] == "app.cli:main"

    from app.cli import main

    assert callable(main)


def test_cli_accepts_host_port_and_log_level() -> None:
    from app.cli import _build_parser

    args = _build_parser().parse_args(
        ["--host", "127.0.0.1", "--port", "9999", "--log-level", "debug"]
    )
    assert (args.host, args.port, args.log_level) == ("127.0.0.1", 9999, "debug")


def test_wheel_carries_the_dashboard(pyproject: dict) -> None:
    """Drop this mapping and the wheel ships an API with no UI behind `/`."""
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["app", "packages"]
    assert wheel["force-include"]["design"] == "app/design"


def test_design_dir_resolves_in_a_repo_checkout() -> None:
    from app.main import _find_design_dir

    found = _find_design_dir()
    assert found is not None
    assert Path(found).resolve() == (REPO_ROOT / "design").resolve()
    assert (Path(found) / "index.html").is_file()


def test_design_dir_honours_the_env_override(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("ORCA_DESIGN_DIR", str(tmp_path))

    from app.main import _find_design_dir

    assert Path(_find_design_dir()).resolve() == tmp_path.resolve()


def test_start_script_delegates_to_the_cli() -> None:
    """Docker CMD runs scripts/start.py, the wheel runs app.cli — one code path.

    `scripts/` is not part of the wheel, so the boot logic cannot live there.
    """
    source = (REPO_ROOT / "scripts" / "start.py").read_text(encoding="utf-8")
    assert "from app.cli import main" in source
