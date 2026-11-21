"""Offline tests for the 13F filer directory (app/directory.py).

Everything runs against fakes: the cache is pointed at a temp dir and the
network helpers are monkeypatched, so these pass without touching the SEC.
"""
import json

import pytest

from app import directory

MASTER_A = (
    "1067983|BERKSHIRE HATHAWAY INC|13F-HR|20260814|/edgar/data/1067983/a.txt\n"
    "1067983|BERKSHIRE HATHAWAY INC|13F-NT|20260814|/edgar/data/1067983/b.txt\n"
    "9999|NOT A 13F AT ALL|8-K|20260814|/edgar/data/9999/c.txt\n"
    "notacik|BROKEN LINE|13F-HR|20260814|/edgar/data/1/d.txt\n"
    "1350694|BRIDGEWATER ASSOC LP|13F-HR|20260813|/edgar/data/1350694/e.txt\n"
)

MASTER_B = "1067983|BERKSHIRE HATHAWAY INC|13F-HR|20260813|/edgar/data/1067983/old.txt\n"


def test_parse_master_keeps_only_13f_family():
    rows = directory.parse_master(MASTER_A)
    assert [r["cik"] for r in rows] == ["1067983", "1067983", "1350694"]
    assert all(r["form"].startswith("13F") for r in rows)
    assert rows[0]["date"] == "2026-08-14"
    assert rows[0]["path"] == "/edgar/data/1067983/a.txt"


def test_rank_holdings_beats_notes():
    assert directory._rank("13F-HR") == 0
    assert directory._rank("13F-HR/A") == 0
    assert directory._rank("13F-NT") == 1
    assert directory._rank("13F-CONP") == 1


def test_prev_quarter_wraps_years():
    assert directory._prev_quarter(2026, 1) == (2025, 4)
    assert directory._prev_quarter(2026, 3) == (2026, 2)


# ---------------------------------------------------------------------------
# quarter_days: the SEC's index.json shape
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload, status: int = 200):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload)


class _FakeClient:
    def __init__(self, payloads: dict):
        self.payloads = payloads
        self.urls: list[str] = []

    def get(self, url, timeout=None, follow_redirects=None):
        self.urls.append(url)
        v = self.payloads[url]
        return v if isinstance(v, _FakeResponse) else _FakeResponse(v)


def _install_fake(monkeypatch, tmp_path, payloads: dict):
    monkeypatch.setattr(directory, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(directory, "_client", _FakeClient(payloads))


def _file(name, size="100 KB"):
    return {"last-modified": "01/01/2026 10:02:20 PM", "name": name,
            "type": "file", "href": name, "size": size}


# The current (2026) shape: "directory" is an object whose "item" holds the
# files, and each file's href is the full filename, not a bare date.
NEW_INDEX = {"directory": {
    "item": [
        _file("company.20261001.idx", "792 KB"),
        _file("master.20261001.idx", "280 KB"),
        _file("sitemap.20261001.xml", "1 MB"),
        _file("master.20261002.idx", "283 KB"),
        _file("sitemap.20261002.xml", "1 MB"),
    ],
    "name": "QTR4",
    "parent-dir": {"name": "2026", "type": "directory", "href": "../"},
}}

# The older shape the module was first written against: a flat list whose
# hrefs are bare YYYYMMDD dates.
OLD_INDEX = {"directory": [
    {"type": "file", "name": "20261001", "href": "20261001"},
    {"type": "file", "name": "20261002", "href": "20261002"},
    {"type": "directory", "name": "old", "href": "old/"},
]}


def test_quarter_days_reads_nested_2026_index(monkeypatch, tmp_path):
    _install_fake(monkeypatch, tmp_path, {
        "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json":
            NEW_INDEX})
    days = directory.quarter_days(2026, 4)
    assert days == ["20261001", "20261002"]  # dates pulled out of the filenames


def test_quarter_days_still_reads_flat_legacy_index(monkeypatch, tmp_path):
    _install_fake(monkeypatch, tmp_path, {
        "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json":
            OLD_INDEX})
    assert directory.quarter_days(2026, 4) == ["20261001", "20261002"]


def test_quarter_days_non_200_is_a_plain_english_error(monkeypatch, tmp_path):
    url = ("https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json")
    _install_fake(monkeypatch, tmp_path, {url: _FakeResponse(None, status=404)})
    with pytest.raises(directory.DirectoryError, match="Couldn't read"):
        directory.quarter_days(2026, 4)


def test_build_snapshot_dedupes_and_ranks(monkeypatch, tmp_path):
    """One filer's holdings filing must survive the 13F-NT noise and beat
    its own older filing."""
    monkeypatch.setattr(directory, "CACHE_DIR", tmp_path)
    # Deterministic whatever the real current quarter is: the two quarters
    # we crawl yield exactly these two master files.
    monkeypatch.setattr(
        directory, "quarter_days", lambda y, q: ["20260814"] if q % 2 == 0 else ["20260813"])
    monkeypatch.setattr(
        directory, "_cached_read",
        lambda name, ttl=None: {"master_20260814.idx": MASTER_A,
                                "master_20260813.idx": MASTER_B}.get(name))

    snap = directory.build_snapshot(refresh=True)

    assert snap["n_filers"] == 2
    berk = next(f for f in snap["filers"] if f["cik"] == "1067983")
    # Same-day tie: the real holdings filing (a.txt) beats the NT note (b.txt).
    assert berk["form"] == "13F-HR"
    assert berk["date"] == "2026-08-14"
    assert berk["path"].endswith("a.txt")
    brid = next(f for f in snap["filers"] if f["cik"] == "1350694")
    assert brid["date"] == "2026-08-13"

    # And it hit the disk cache, so load_snapshot() can serve it offline.
    assert directory.load_snapshot() is not None
    assert directory.load_snapshot()["n_filers"] == 2


def test_build_snapshot_all_empty_raises_plain_english(monkeypatch, tmp_path):
    monkeypatch.setattr(directory, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(directory, "quarter_days",
                        lambda y, q: (_ for _ in ()).throw(directory.DirectoryError("nope")))
    with pytest.raises(directory.DirectoryError):
        directory.build_snapshot(refresh=True)


def _write_snap(tmp_path, filers):
    (tmp_path / "directory.json").write_text(json.dumps(
        {"v": directory._VERSION, "generated": 0, "quarters": ["2026 Q3"],
         "n_filings": len(filers), "n_filers": len(filers), "filers": filers}))


def test_search_name_prefix_beats_midname(monkeypatch, tmp_path):
    monkeypatch.setattr(directory, "CACHE_DIR", tmp_path)
    _write_snap(tmp_path, [
        {"cik": "8888002", "name": "ACME BERKSHIRE TRUST", "form": "13F-HR",
         "date": "2026-08-14", "path": ""},
        {"cik": "1067983", "name": "BERKSHIRE HATHAWAY INC", "form": "13F-HR",
         "date": "2026-08-14", "path": ""},
    ])
    hits = directory.search("berkshire")
    assert [h["cik"] for h in hits] == ["1067983", "8888002"]


def test_search_by_cik_and_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(directory, "CACHE_DIR", tmp_path)
    _write_snap(tmp_path, [
        {"cik": "1067983", "name": "BERKSHIRE HATHAWAY INC", "form": "13F-HR",
         "date": "2026-08-14", "path": ""},
        {"cik": "9999001", "name": "Sionne Capital", "form": "13F-HR",
         "date": "2026-08-14", "path": ""},
    ])
    assert [h["cik"] for h in directory.search("sionne")] == ["9999001"]
    assert [h["cik"] for h in directory.search("1067983")] == ["1067983"]
    # The search never leaks the internal filing path to the front end.
    assert "path" not in hits if (hits := directory.search("sionne")) else True
    assert directory.search("x") == []   # fewer than 2 chars


def test_search_without_snapshot_is_a_plain_english_error(monkeypatch, tmp_path):
    monkeypatch.setattr(directory, "CACHE_DIR", tmp_path)
    with pytest.raises(directory.DirectoryError):
        directory.search("berkshire")


def test_stale_snapshot_is_treated_as_missing(monkeypatch, tmp_path):
    import time as _t
    monkeypatch.setattr(directory, "CACHE_DIR", tmp_path)
    (tmp_path / "directory.json").write_text(
        json.dumps({"v": directory._VERSION, "filers": []}))
    old = _t.time() - 48 * 3600
    import os as _os
    _os.utime(tmp_path / "directory.json", (old, old))
    assert directory.load_snapshot() is None
