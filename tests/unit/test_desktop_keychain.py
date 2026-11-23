"""Desktop secrets live in the OS keychain when there is one.

The encryption key and key pepper protect every provider key the user saves,
so on macOS (Keychain), Windows (Credential Manager) and Linux desktops
(Secret Service) they're kept in the OS keychain instead of a file. A secrets
file from an earlier version moves into the keychain, and is deleted only
after the keychain hands the same values back. Where no keychain works
(headless Linux, CI, ORCA_KEYCHAIN=0) the 0600 file stays the store.
"""

from __future__ import annotations

import json
import os
import stat
import threading

import pytest

from packages.desktop import home as dh


class FakeKeychain:
    def __init__(self, *, fail_set=False, fail_get=False, drop_writes=False):
        self.items: dict[str, str] = {}
        self.fail_set, self.fail_get, self.drop_writes = fail_set, fail_get, drop_writes
        self.lock = threading.Lock()

    def get(self, name):
        if self.fail_get:
            raise RuntimeError("locked")
        with self.lock:
            return self.items.get(name)

    def set(self, name, value):
        if self.fail_set:
            raise RuntimeError("denied")
        if not self.drop_writes:
            with self.lock:
                self.items[name] = value


def _file(home):
    return home / "secrets.json"


def _valid(secrets):
    return bool(secrets["credential_encryption_key"]) and bool(secrets["api_key_pepper"])


def test_new_install_keeps_secrets_in_the_keychain_not_on_disk(tmp_path):
    home, kc = tmp_path / "orca", FakeKeychain()
    first = dh.prepare_home(home, keychain=kc)
    assert _valid(first)
    assert not _file(home).exists()
    [stored] = kc.items.values()
    assert json.loads(stored) == first
    assert dh.prepare_home(home, keychain=kc) == first  # stable across launches


def test_an_existing_secrets_file_moves_into_the_keychain(tmp_path):
    home = tmp_path / "orca"
    old = dh.prepare_home(home, keychain=None)  # an earlier version wrote the file
    assert _file(home).exists()
    kc = FakeKeychain()
    assert dh.prepare_home(home, keychain=kc) == old
    assert not _file(home).exists()
    assert json.loads(next(iter(kc.items.values()))) == old


def test_the_file_is_kept_when_the_keychain_does_not_hand_the_secrets_back(tmp_path):
    home = tmp_path / "orca"
    old = dh.prepare_home(home, keychain=None)
    assert dh.prepare_home(home, keychain=FakeKeychain(drop_writes=True)) == old
    assert _file(home).exists()


@pytest.mark.parametrize("kc", [FakeKeychain(fail_set=True), FakeKeychain(fail_get=True)])
def test_a_broken_keychain_falls_back_to_the_private_file(tmp_path, kc):
    home = tmp_path / "orca"
    secrets = dh.prepare_home(home, keychain=kc)
    assert _valid(secrets)
    assert stat.S_IMODE(os.stat(_file(home)).st_mode) == 0o600
    assert dh.prepare_home(home, keychain=kc) == secrets


def test_when_file_and_keychain_disagree_the_file_wins_and_nothing_is_deleted(tmp_path):
    # Only a restored backup or a manual edit gets here; the file is what the
    # database was last used with, so don't throw it away.
    home = tmp_path / "orca"
    on_disk = dh.prepare_home(home, keychain=None)
    kc = FakeKeychain()
    kc.items[dh.keychain_name(home)] = json.dumps({"credential_encryption_key": "x", "api_key_pepper": "y"})
    assert dh.prepare_home(home, keychain=kc) == on_disk
    assert _file(home).exists()


def test_two_homes_never_share_secrets(tmp_path):
    kc = FakeKeychain()
    a = dh.prepare_home(tmp_path / "a", keychain=kc)
    b = dh.prepare_home(tmp_path / "b", keychain=kc)
    assert a != b
    assert len(kc.items) == 2


def test_concurrent_first_runs_agree_on_the_secrets(tmp_path):
    home, kc = tmp_path / "orca", FakeKeychain()
    results = []
    threads = [threading.Thread(target=lambda: results.append(dh.prepare_home(home, keychain=kc))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({json.dumps(r, sort_keys=True) for r in results}) == 1


def test_keychain_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("ORCA_KEYCHAIN", "0")
    assert dh.system_keychain() is None


def test_an_unusable_keyring_backend_means_no_keychain(monkeypatch):
    import keyring
    from keyring.backends import fail

    monkeypatch.delenv("ORCA_KEYCHAIN", raising=False)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1/bus")
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    assert dh.system_keychain() is None


def test_a_working_keyring_backend_is_used(monkeypatch):
    import keyring

    class Backend:
        priority = 5
        store: dict = {}

        def get_password(self, service, name):
            return self.store.get((service, name))

        def set_password(self, service, name, value):
            self.store[(service, name)] = value

    monkeypatch.delenv("ORCA_KEYCHAIN", raising=False)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1/bus")
    monkeypatch.setattr(keyring, "get_keyring", Backend)
    kc = dh.system_keychain()
    assert kc is not None
    kc.set("secrets:/x", "v")
    assert kc.get("secrets:/x") == "v"
    assert Backend.store == {("OrcaRouter Lite", "secrets:/x"): "v"}


def test_headless_linux_keeps_the_file(monkeypatch):
    monkeypatch.delenv("ORCA_KEYCHAIN", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setattr(dh.sys, "platform", "linux")
    assert dh.system_keychain() is None


def test_desktop_env_uses_the_keychain(tmp_path, monkeypatch):
    kc = FakeKeychain()
    monkeypatch.setattr(dh, "system_keychain", lambda: kc)
    env = dh.desktop_env(tmp_path / "orca")
    assert env["CREDENTIAL_ENCRYPTION_KEY"] == json.loads(next(iter(kc.items.values())))["credential_encryption_key"]
    assert not _file(tmp_path / "orca").exists()
