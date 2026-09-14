"""Tests for Settings field validators.

The validators catch misconfiguration at startup — an out-of-range port
or a negative retry count should fail fast with a clear message rather
than propagating to uvicorn / LiteLLM Router and producing a confusing
runtime error deep in the stack.
"""

import pytest


def test_port_default_is_valid(isolated_env):
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.port == 8000


def test_port_boundary_low(isolated_env):
    from app.config import Settings

    s = Settings(_env_file=None, port=1)
    assert s.port == 1


def test_port_boundary_high(isolated_env):
    from app.config import Settings

    s = Settings(_env_file=None, port=65535)
    assert s.port == 65535


def test_port_zero_rejected(isolated_env):
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="port must be 1"):
        Settings(_env_file=None, port=0)


def test_port_negative_rejected(isolated_env):
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="port must be 1"):
        Settings(_env_file=None, port=-1)


def test_port_above_max_rejected(isolated_env):
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="port must be 1"):
        Settings(_env_file=None, port=70000)


def test_cooldown_zero_allowed(isolated_env):
    """Tests set 0 to disable cooldown entirely — must remain valid."""
    from app.config import Settings

    s = Settings(_env_file=None, router_cooldown_seconds=0)
    assert s.router_cooldown_seconds == 0


def test_cooldown_negative_rejected(isolated_env):
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="router_cooldown_seconds must be >= 0"):
        Settings(_env_file=None, router_cooldown_seconds=-10)


def test_allowed_fails_default_zero(isolated_env):
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.router_allowed_fails == 0


def test_allowed_fails_negative_rejected(isolated_env):
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="router_allowed_fails must be >= 0"):
        Settings(_env_file=None, router_allowed_fails=-1)


def test_retries_default_allowed(isolated_env):
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.router_num_retries_default == 2
    assert s.router_num_retries_auto == 0


def test_retries_negative_rejected(isolated_env):
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="router_num_retries_default must be >= 0"):
        Settings(_env_file=None, router_num_retries_default=-1)

    with pytest.raises(ValidationError, match="router_num_retries_auto must be >= 0"):
        Settings(_env_file=None, router_num_retries_auto=-3)


def test_port_via_env_rejected(isolated_env, monkeypatch):
    """Env-sourced port still runs through the validator."""
    from app.config import Settings
    from pydantic import ValidationError

    monkeypatch.setenv("PORT", "99999")
    with pytest.raises(ValidationError, match="port must be 1"):
        Settings(_env_file=None)
