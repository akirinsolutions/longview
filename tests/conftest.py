"""Suite-wide fixtures.

The one thing every test must not do is touch the reader's real data
file. The vault's address is a single module attribute
(``app.vault.VAULT_PATH``); an autouse fixture points it at a fresh
scratch file per test, so no test — new or old — reads or writes
``data/longview.json``.
"""
import pytest

from app import vault


@pytest.fixture(autouse=True)
def _vault_to_tmp(tmp_path, monkeypatch):
    # The vault file and the legacy-file search both land in the test's
    # scratch directory, so a test that corrupts the vault reads back an
    # empty vault — never the developer's real data.
    monkeypatch.setattr(vault, "VAULT_PATH", tmp_path / "longview.json")
    monkeypatch.setattr(vault, "LEGACY_DIR", tmp_path)
    yield
