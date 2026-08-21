"""redacted_url() must never leak credentials into loggable strings."""

from __future__ import annotations


def test_hides_password_on_postgres_style_url():
    from packages.db.engine import redacted_url

    out = redacted_url("postgresql+asyncpg://user:sup3rsecret@db.example.com:5432/orca")
    assert "sup3rsecret" not in out
    assert out.startswith("postgresql+asyncpg://user:")
    assert "@db.example.com:5432/orca" in out


def test_password_free_url_survives_intact():
    from packages.db.engine import redacted_url

    url = "sqlite+aiosqlite:///./orca.db"
    assert redacted_url(url) == url


def test_unparseable_input_is_replaced_not_echoed():
    from packages.db.engine import redacted_url

    garbage = "://not a url at all\x00"
    assert redacted_url(garbage) == "<unparseable-database-url>"
