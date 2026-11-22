"""Offline tests for the fund roster (the user's editable list of funds).

The roster file is pointed at a temp dir for the whole module's tests, so
the real data/roster.json is never touched.
"""
import json

import pytest

from app import funds, vault


@pytest.fixture
def roster_path(tmp_path, monkeypatch):
    # The roster is a section of the one vault file; the file this
    # fixture points at is the vault file itself.
    p = tmp_path / "longview.json"
    monkeypatch.setattr(vault, "VAULT_PATH", p)
    return p


def _seeded_roster():
    return {f["key"] for f in funds.active_roster()}


def test_active_roster_seeds_from_defaults(roster_path):
    roster = funds.active_roster()
    assert [f["key"] for f in roster][:3] == ["berkshire", "bridgewater", "deshaw"]
    assert len(roster) == len(funds.FUNDS)
    assert roster_path.exists()
    saved = json.loads(roster_path.read_text())["sections"]["roster"]
    assert saved["v"] == funds._ROSTER_VERSION
    assert [f["key"] for f in saved["funds"]] == [f["key"] for f in roster]


def test_saved_roster_wins_over_defaults(roster_path):
    # The user removed pershing and added a custom one: that must survive.
    entries = [dict(f) for f in funds.FUNDS]
    entries = [f for f in entries if f["key"] != "pershing"]
    entries.append({"key": "sionne", "name": "Sionne", "manager": "", "cik": 9999001})
    funds._save_roster(entries)
    keys = {f["key"] for f in funds.active_roster()}
    assert "sionne" in keys and "pershing" not in keys


def test_corrupt_roster_falls_back_to_defaults(roster_path):
    roster_path.write_text("{ definitely not json")
    keys = _seeded_roster()
    assert keys == {f["key"] for f in funds.FUNDS}


def test_saved_roster_picks_up_corrected_manager_labels(roster_path):
    # Curated metadata lives in code; an older saved roster must not
    # keep showing a stale (wrong) manager name forever.
    entries = [dict(f) for f in funds.FUNDS]
    entries[0]["manager"] = "Someone Else"
    funds._save_roster(entries)
    roster = funds.active_roster()
    assert roster[0]["manager"] == funds.FUNDS[0]["manager"]
    saved = json.loads(roster_path.read_text())["sections"]["roster"]
    assert saved["funds"][0]["manager"] == funds.FUNDS[0]["manager"]


def test_cached_pool_gets_curated_labels_but_not_user_funds():
    pool = {"funds": [
        {"key": "tiger", "name": "Tiger Global", "manager": "Old Label"},
        {"key": "custom", "name": "My Fund", "manager": "Me"},
    ]}
    out = funds._apply_curated_metadata(pool)
    assert out["funds"][0]["manager"] == "Chase Coleman"
    assert out["funds"][1] == {"key": "custom", "name": "My Fund", "manager": "Me"}


def _fresh_cik_sub(form="13F-HR", date="2026-08-14"):
    return {"filings": {"recent": {"form": [form], "filingDate": [date]}}}


def test_add_fund_appends_and_saves(roster_path, monkeypatch):
    funds.active_roster()
    monkeypatch.setattr(funds, "_submissions", lambda cik10: _fresh_cik_sub())
    entry, roster = funds.add_fund("SIONNE CAPITAL /NY/", "9999001")
    assert entry["name"] == "SIONNE CAPITAL"      # /NY/ stripped; EDGAR names stay official-caps
    assert entry["manager"] == ""
    assert entry["cik"] == 9999001                # stored as an int
    assert roster[-1] == entry
    saved = json.loads(roster_path.read_text())["sections"]["roster"]
    assert len(saved["funds"]) == len(funds.FUNDS) + 1


def test_add_rejects_filer_already_on_roster(roster_path, monkeypatch):
    def _never(*a, **k):
        raise AssertionError("already-on-roster check must happen before any SEC call")
    funds.active_roster()
    monkeypatch.setattr(funds, "_submissions", _never)
    with pytest.raises(ValueError, match="already on the roster"):
        funds.add_fund("Whatever Name", 1067983)   # berkshire's CIK


def test_add_rejects_non_numeric_cik(roster_path):
    funds.active_roster()
    with pytest.raises(ValueError, match="isn't a number"):
        funds.add_fund("Some Fund", "twelve")


def test_add_rejects_filings_only_notes(roster_path, monkeypatch):
    funds.active_roster()
    monkeypatch.setattr(funds, "_submissions", lambda cik10: _fresh_cik_sub(form="13F-NT"))
    with pytest.raises(RuntimeError, match="not filing this quarter"):
        funds.add_fund("Quiet Fund", 1111111)


def test_add_rejects_stale_filer(roster_path, monkeypatch):
    funds.active_roster()
    monkeypatch.setattr(funds, "_submissions",
                        lambda cik10: _fresh_cik_sub(date="2023-01-14"))
    with pytest.raises(RuntimeError, match="too stale"):
        funds.add_fund("Sleepy Fund", 2222222)


def test_add_rejects_filer_without_13f_history(roster_path, monkeypatch):
    funds.active_roster()
    monkeypatch.setattr(
        funds, "_submissions",
        lambda cik10: {"filings": {"recent": {"form": ["10-K", "8-K"],
                                              "filingDate": ["2026-01-01", "2026-02-02"]}}})
    with pytest.raises(RuntimeError, match="no recent 13F history"):
        funds.add_fund("Corporation", 3333333)


def test_add_makes_unique_keys_for_lookalike_names(roster_path, monkeypatch):
    # Two filers whose names normalize to the same base get suffixed keys.
    funds.active_roster()
    monkeypatch.setattr(funds, "_submissions", lambda cik10: _fresh_cik_sub())
    e1, _ = funds.add_fund("DUAL FUND PARTNERS", 4444001)
    e2, roster = funds.add_fund("dual fund partners", 4444002)
    assert e1["key"] == "dualfundpartners"
    assert e2["key"] == "dualfundpartners2"
    assert {f["key"] for f in roster} >= {e1["key"], e2["key"]}


def test_remove_fund_saves_the_smaller_roster(roster_path):
    funds.active_roster()
    removed, roster = funds.remove_fund("pershing")
    assert removed["key"] == "pershing"
    assert "pershing" not in {f["key"] for f in roster}
    saved = json.loads(roster_path.read_text())["sections"]["roster"]["funds"]
    assert "pershing" not in {f["key"] for f in saved}
    assert len(saved) == len(funds.FUNDS) - 1


def test_remove_unknown_key_is_a_keyerror(roster_path):
    funds.active_roster()
    with pytest.raises(KeyError):
        funds.remove_fund("nope")


def test_last_fund_cannot_be_removed(roster_path):
    funds._save_roster([{"key": "solo", "name": "Solo Fund",
                         "manager": "", "cik": 5555555}])
    with pytest.raises(ValueError, match="only fund"):
        funds.remove_fund("solo")
    # And nothing was written.
    assert [f["key"] for f in funds.active_roster()] == ["solo"]


def test_fingerprint_changes_with_the_roster(roster_path, monkeypatch):
    funds.active_roster()
    fp1 = funds.roster_fingerprint()
    monkeypatch.setattr(funds, "_submissions", lambda cik10: _fresh_cik_sub())
    entry, _ = funds.add_fund("New Fund", 6666001)
    assert funds.roster_fingerprint() != fp1
    # Remove it again -> the fingerprint comes back to exactly what it was.
    funds.remove_fund(entry["key"])
    assert funds.roster_fingerprint() == fp1


def test_get_fund_reads_the_active_roster(roster_path):
    assert funds.get_fund("berkshire") is not None
    assert funds.get_fund("nope") is None
    # A removed fund is no longer findable.
    funds.remove_fund("citadel")
    assert funds.get_fund("citadel") is None
