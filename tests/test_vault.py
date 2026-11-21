"""The vault: one file for everything the reader owns.

The suite-wide conftest fixture already points ``VAULT_PATH`` and
``LEGACY_DIR`` at the test's scratch directory, so none of this can
touch the real ``data/`` folder.
"""
import json

import pytest

from app import vault


def _envelope(name, **keys):
    return {"v": 1, "updated": 0,
             **{k: v for k, v in keys.items()}}


# ---------------------------------------------------------------------------
# load / read_section / write_section
# ---------------------------------------------------------------------------

def test_clean_machine_reads_as_skeleton_and_writes_nothing():
    v = vault.load()
    assert v["v"] == vault.VERSION
    assert v["updated"] == 0
    assert list(v["sections"]) == list(vault.SECTIONS)
    assert all(s is None for s in v["sections"].values())
    assert not vault.VAULT_PATH.exists()


def test_write_section_roundtrips_and_touches_updated():
    env = _envelope("portfolio", positions=[{"ticker": "AAPL"}])
    vault.write_section("portfolio", env)

    assert vault.VAULT_PATH.exists()
    assert vault.read_section("portfolio") == env
    raw = json.loads(vault.VAULT_PATH.read_text())
    assert raw["sections"]["portfolio"]["positions"] == [{"ticker": "AAPL"}]
    assert raw["updated"] > 0
    # The other sections are present as null, not missing.
    assert raw["sections"]["notes"] is None


def test_write_section_none_drops_it():
    vault.write_section("notes", _envelope("notes", pages=[]))
    assert vault.read_section("notes") is not None
    vault.write_section("notes", None)
    assert vault.read_section("notes") is None


def test_unknown_section_is_a_keyerror():
    with pytest.raises(KeyError):
        vault.read_section("nope")
    with pytest.raises(KeyError):
        vault.write_section("nope", {})


def test_sections_keep_their_old_envelope_bytes():
    # The point of the design: each section is exactly the file its
    # module used to own, so a saved section reads back unchanged.
    env = _envelope("roster", funds=[{"key": "sionne"}])
    vault.write_section("roster", env)
    assert vault.read_section("roster") == env


# ---------------------------------------------------------------------------
# The one-time legacy fold
# ---------------------------------------------------------------------------

def test_legacy_files_fold_in_and_research_moves_notes_to_reports():
    (vault.LEGACY_DIR / "portfolio.json").write_text(
        json.dumps(_envelope("portfolio", positions=[{"ticker": "AAPL"}])))
    (vault.LEGACY_DIR / "study.json").write_text(json.dumps(
        {"v": 1, "updated": 5, "notes": [{"id": "r-1", "kind": "ai",
                                          "title": "T", "body": "b"}]}))
    (vault.LEGACY_DIR / "economy_tree.json").write_text(json.dumps(
        {"version": 1, "updated": "2026-01-01T00:00:00Z",
         "tree": {"name": "x"}}))

    v = vault.load()
    assert v["sections"]["portfolio"]["positions"] == [{"ticker": "AAPL"}]
    assert v["sections"]["research"]["reports"] == [
        {"id": "r-1", "kind": "ai", "title": "T", "body": "b"}]
    assert v["sections"]["economy"]["tree"]["name"] == "x"
    assert v["sections"]["notes"] is None
    assert v["updated"] > 0
    assert vault.VAULT_PATH.exists()


def test_corrupt_vault_with_legacy_folds_the_legacy():
    vault.VAULT_PATH.write_text("{ not json")
    (vault.LEGACY_DIR / "risk.json").write_text(
        json.dumps(_envelope("risk", moves={"AAPL": 1.0})))
    v = vault.load()
    assert v["sections"]["risk"]["moves"] == {"AAPL": 1.0}
    assert v["sections"]["portfolio"] is None


def test_corrupt_vault_on_clean_machine_is_empty():
    vault.VAULT_PATH.write_text("{ not json")
    v = vault.load()
    assert all(s is None for s in v["sections"].values())


def test_wrong_vault_version_reads_as_missing():
    vault.VAULT_PATH.write_text(json.dumps(
        {"v": 99, "updated": 0, "sections": {}}))
    v = vault.load()
    assert all(s is None for s in v["sections"].values())


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------

def test_meta_reports_presence_and_counts():
    vault.write_section("portfolio",
                        _envelope("portfolio",
                                  positions=[{"ticker": "A"},
                                             {"ticker": "B"}]))
    vault.write_section("risk", _envelope("risk", moves={"A": 1.0}))
    m = vault.meta()
    assert m["sections"]["portfolio"] is True
    assert m["sections"]["portfolio_count"] == 2
    assert m["sections"]["risk"] is True
    assert m["sections"]["risk_count"] == 1
    assert m["sections"]["notes"] is False


def test_meta_empty_vault():
    m = vault.meta()
    assert m["updated"] == 0
    for k, v in m["sections"].items():
        assert v is False, k          # no section, hence no count key


# ---------------------------------------------------------------------------
# replace (the import path)
# ---------------------------------------------------------------------------

def test_replace_full_vault_file():
    src = {"v": 1, "updated": 77,
           "sections": {"notes": _envelope("notes", pages=[{"id": "n1"}])}}
    meta = vault.replace(src)
    assert vault.read_section("notes") == src["sections"]["notes"]
    assert vault.read_section("portfolio") is None
    assert meta["updated"] == 77


def test_replace_sections_block():
    src = {"notes": _envelope("notes", pages=[{"id": "n1"}])}
    vault.replace(src)
    assert vault.read_section("notes") is not None


def test_replace_drops_unknown_section_names():
    vault.replace({"notes": _envelope("notes", pages=[]),
                   "bogus": {"v": 1}})
    assert vault.read_section("notes") is not None
    assert "bogus" not in vault.load()["sections"]


def test_replace_rejects_a_file_that_is_not_a_vault():
    with pytest.raises(ValueError):
        vault.replace({"hello": "world"})
    with pytest.raises(ValueError):
        vault.replace("not json at all")


def test_replace_bad_updated_becomes_now():
    vault.replace({"v": 1, "updated": "soon",
                   "sections": {"notes": _envelope("notes", pages=[])}})
    m = vault.meta()
    assert m["updated"] > 0


# ---------------------------------------------------------------------------
# The routes: GET/PUT /api/vault
# ---------------------------------------------------------------------------

def _client():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_vault_get_is_the_file():
    c = _client()
    r = c.get("/api/vault")
    assert r.status_code == 200
    body = r.json()
    assert body["v"] == vault.VERSION
    assert set(body["sections"]) == set(vault.SECTIONS)


def test_vault_put_imports_and_get_reflects():
    c = _client()
    src = {"v": 1, "updated": 77,
           "sections": {"portfolio":
                        _envelope("portfolio",
                                  positions=[{"ticker": "AAPL"}])}}
    r = c.put("/api/vault", json=src)
    assert r.status_code == 200
    assert r.json()["updated"] == 77
    body = c.get("/api/vault").json()
    assert body["sections"]["portfolio"]["positions"] == [
        {"ticker": "AAPL"}]


def test_vault_put_rejects_garbage():
    c = _client()
    r = c.put("/api/vault", content=b"{ not json",
              headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_vault_put_rejects_unknown_shape():
    c = _client()
    r = c.put("/api/vault", json={"hello": "world"})
    assert r.status_code == 400


def test_vault_put_rejects_huge_files():
    c = _client()
    big = json.dumps({"v": 1, "updated": 1,
                      "sections": {"notes": _envelope(
                          "notes", pages=[{"id": "n", "body": "x" * 5_000_000}])}})
    r = c.put("/api/vault", content=big,
              headers={"content-type": "application/json"})
    assert r.status_code == 413
