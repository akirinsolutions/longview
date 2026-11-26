"""Suite-wide fixtures.

The one thing every test must not do is touch the reader's real data
file. The vault's address is a single module attribute
(``app.vault.VAULT_PATH``); an autouse fixture points it at a fresh
scratch file per test, so no test — new or old — reads or writes
``data/longview.json``. The same is true of the accounts store and
the per-person user files, so a signed-in test touches only its own
scratch directory.
"""
import pytest

from app import accounts, vault


@pytest.fixture(autouse=True)
def _vault_to_tmp(tmp_path, monkeypatch):
    # The vault file and the legacy-file search both land in the test's
    # scratch directory, so a test that corrupts the vault reads back an
    # empty vault — never the developer's real data.
    monkeypatch.setattr(vault, "VAULT_PATH", tmp_path / "longview.json")
    monkeypatch.setattr(vault, "LEGACY_DIR", tmp_path)
    monkeypatch.setattr(vault, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(accounts, "ACCOUNTS_PATH", tmp_path / "accounts.json")
    monkeypatch.setattr(accounts, "SECRET_PATH", tmp_path / "secret.key")
    accounts._FAILURES.clear()
    yield
