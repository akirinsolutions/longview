"""13F parsing, diffing, and crowded-name logic on fixtures (no network)."""
import json

from app import funds

NEW_FORMAT = """
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>1000000</value>
    <shrsOrPrnAmt><sshPrnamt>2000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>500000</value>
    <shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>Microsoft Corp</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>594918104</cusip>
    <value>2000000</value>
    <shrsOrPrnAmt><sshPrnamt>3000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>
"""

OLD_FORMAT = """
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <tableData entries="2">
    <nameOfIssuer>AAA CORP</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <value>500</value><shrs>10</shrs>
    <nameOfIssuer>BBB CO</nameOfIssuer><titleOfClass>PREF</titleOfClass>
    <value>900</value><shrs>5</shrs>
  </tableData>
</informationTable>
"""


def test_parse_new_format_merges_duplicate_issuers():
    pos = funds.parse_info_table(NEW_FORMAT)
    assert len(pos) == 2  # the two APPLE rows merge
    assert pos[0]["issuer"] == "Microsoft Corp"
    assert pos[0]["value"] == 2_000_000
    assert pos[1]["issuer"] == "APPLE INC"
    assert pos[1]["value"] == 1_500_000  # 1M + 0.5M
    assert pos[1]["shares"] == 3000


def test_parse_old_flat_format():
    pos = funds.parse_info_table(OLD_FORMAT)
    assert [p["issuer"] for p in pos] == ["BBB CO", "AAA CORP"]  # sorted by value
    assert pos[0]["value"] == 900


def test_normalize_name():
    assert funds.normalize_name("ALLY FINL INC") == "ALLY FINL"
    assert funds.normalize_name("Apple Inc.") == "APPLE"
    assert funds.normalize_name("3M Co") == "3M"


def test_diff_added_exited_and_moves():
    latest = [
        {"issuer": "Alpha Corp", "class": "COM", "value": 1e8, "shares": 1},
        {"issuer": "Beta Inc", "class": "COM", "value": 1e7, "shares": 1},
        {"issuer": "Gamma LLC", "class": "COM", "value": 8e7, "shares": 1},
    ]
    prev = [
        {"issuer": "Alpha Corp", "class": "COM", "value": 5e7, "shares": 1},
        {"issuer": "Beta Inc", "class": "COM", "value": 1e7, "shares": 1},
        {"issuer": "Delta Co", "class": "COM", "value": 9e7, "shares": 1},
    ]
    added, exited, moves = funds._diff_positions(latest, prev)
    assert [p["issuer"] for p in added] == ["Gamma LLC"]
    assert [p["issuer"] for p in exited] == ["Delta Co"]
    # Alpha doubled (1x) and is big enough to count as a move; Beta didn't change
    assert [p["issuer"] for p in moves] == ["Alpha Corp"]
    assert abs(moves[0]["change"] - 1.0) < 1e-9


def test_diff_same_cusip_different_names_is_not_added_and_exited():
    # A company renames itself between filings: same CUSIP, different name.
    latest = [{"issuer": "Bank of Amer", "class": "COM", "cusip": "060515104",
               "value": 2e8, "shares": 1}]
    prev = [{"issuer": "Bank America Corp", "class": "COM", "cusip": "060515104",
             "value": 1e8, "shares": 1}]
    added, exited, moves = funds._diff_positions(latest, prev)
    assert added == [] and exited == []  # same security, just a name change
    assert len(moves) == 1 and abs(moves[0]["change"] - 1.0) < 1e-9


def test_crowded_name_detection():
    a = [{"issuer": "Apple Inc", "class": "COM", "value": 1e9, "shares": 1}]
    b = [{"issuer": "APPLE INC", "class": "COM", "value": 2e9, "shares": 1}]
    c = [{"issuer": "Apple, Inc.", "class": "COM", "value": 5e8, "shares": 1}]
    d = [{"issuer": "Nvidia Corp", "class": "COM", "value": 3e9, "shares": 1}]
    holdings = {}
    for name, pos in (("a", a), ("b", b), ("c", c), ("d", d)):
        for p in pos:
            nm = funds.normalize_name(p["issuer"])
            h = holdings.setdefault(nm, {"name": p["issuer"], "funds": set(), "value": 0.0})
            h["funds"].add(name)
            h["value"] += p["value"]
    crowded = {nm: h for nm, h in holdings.items() if len(h["funds"]) >= 3}
    assert set(crowded) == {"APPLE"}
    assert crowded["APPLE"]["funds"] == {"a", "b", "c"}
    assert crowded["APPLE"]["value"] == 3.5e9


def test_extract_period_from_cover():
    xml = """<document xmlns="http://www.sec.gov/edgar/document/thirteenf">
             <reportingPeriod><startDate>2026-04-01</startDate>
             <endDate>2026-06-30</endDate></reportingPeriod></document>"""
    assert funds._extract_period(xml) == "2026-06-30"
    assert funds._extract_period("<garbage") is None


def test_extract_period_new_gen_cover():
    # The modern cover page writes MM-DD-YYYY; normalize to YYYY-MM-DD.
    cover = """
    <edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
      <headerData><submissionType>13F-HR/A</submissionType>
        <filerInfo><periodOfReport>06-30-2026</periodOfReport></filerInfo>
      </headerData>
      <formData><coverPage>
        <reportCalendarOrQuarter>06-30-2026</reportCalendarOrQuarter>
      </coverPage></formData>
    </edgarSubmission>"""
    assert funds._extract_period(cover) == "2026-06-30"


class _FakeResp:
    def __init__(self, status=200, text="", json_data=None):
        self.status_code = status
        self.text = text
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Serves canned documents, keyed by file name. Records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        r = self.routes.get(url.rsplit("/", 1)[-1])
        return r if r is not None else _FakeResp(status=404)


def _sub_with_13fs(pairs):
    """pairs: list of (form, filingDate, accessionNumber)."""
    return {"filings": {"recent": {
        "form": [p[0] for p in pairs],
        "filingDate": [p[1] for p in pairs],
        "accessionNumber": [p[2] for p in pairs],
    }}}


def test_diff_filings_skips_same_quarter_amendment(monkeypatch):
    # Citadel-style: an amendment (13F-HR/A) reports the same quarter as the
    # original it amends. The diff must reach back to the prior quarter,
    # not compare a quarter against itself.
    sub = _sub_with_13fs([
        ("13F-HR/A", "2026-09-02", "0001104659-26-104387"),  # restated Q2
        ("13F-HR",   "2026-08-14", "0001104659-26-097200"),  # original Q2
        ("13F-HR",   "2026-05-15", "0001104659-26-050000"),  # Q1
    ])
    periods = {
        "000110465926104387": "2026-06-30",
        "000110465926097200": "2026-06-30",
        "000110465926050000": "2026-03-31",
    }
    monkeypatch.setattr(funds, "_filing_period",
                        lambda cik10, a: periods.get(a))
    latest, prev = funds._diff_filings("0001423053", sub)
    assert latest["accession"] == "000110465926104387"
    assert prev["accession"] == "000110465926050000"  # Q1, not the original Q2


def test_diff_filings_uses_previous_when_quarters_differ(monkeypatch):
    sub = _sub_with_13fs([
        ("13F-HR", "2026-08-14", "0001104659-26-097200"),
        ("13F-HR", "2026-05-15", "0001104659-26-050000"),
    ])
    monkeypatch.setattr(funds, "_filing_period",
                        lambda cik10, a: {"000110465926097200": "2026-06-30",
                                          "000110465926050000": "2026-03-31"}.get(a))
    latest, prev = funds._diff_filings("0001423053", sub)
    assert prev["accession"] == "000110465926050000"


def test_diff_filings_falls_back_when_quarters_unknown(monkeypatch):
    # When a quarter can't be determined, keep the old behavior: diff
    # against the next most recent holdings filing.
    sub = _sub_with_13fs([
        ("13F-HR/A", "2026-09-02", "0001104659-26-104387"),
        ("13F-HR",   "2026-08-14", "0001104659-26-097200"),
    ])
    monkeypatch.setattr(funds, "_filing_period", lambda cik10, a: None)
    latest, prev = funds._diff_filings("0001423053", sub)
    assert prev["accession"] == "000110465926097200"


def test_cover_period_reads_smallest_xml_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(funds, "CACHE_DIR", tmp_path)
    cover = """<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
      <headerData><filerInfo><periodOfReport>06-30-2026</periodOfReport>
      </filerInfo></headerData></edgarSubmission>"""
    client = _FakeClient({
        "index.json": _FakeResp(json_data={"directory": {"item": [
            {"name": "infotable.xml", "size": "8129503"},
            {"name": "primary_doc.xml", "size": "2604"},
        ]}}),
        "primary_doc.xml": _FakeResp(text=cover),
        "infotable.xml": _FakeResp(text="<informationTable/>"),
    })
    monkeypatch.setattr(funds, "_get_client", lambda: client)
    assert funds._cover_period("0001423053", "000110465926104387") == "2026-06-30"
    # The 8MB table must never be downloaded just to learn the quarter.
    assert not any("infotable" in c for c in client.calls)
    calls_after = len(client.calls)
    assert funds._cover_period("0001423053", "000110465926104387") == "2026-06-30"
    assert len(client.calls) == calls_after  # second call served from cache


def test_fetch_filing_backfills_missing_period(monkeypatch, tmp_path):
    # An older cache entry (period unknown) gets the quarter backfilled
    # from the cover page, and the cache is updated for next time.
    monkeypatch.setattr(funds, "CACHE_DIR", tmp_path)
    path = tmp_path / "pos_0001423053_000110465926104387.json"
    path.write_text(json.dumps({
        "v": funds._CACHE_VERSION, "cik": "0001423053",
        "accession": "000110465926104387", "period": None,
        "positions": [{"issuer": "APPLE INC", "class": "COM",
                       "cusip": "037833100", "value": 1.0, "shares": 1.0}],
    }))
    cover = """<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
      <headerData><filerInfo><periodOfReport>06-30-2026</periodOfReport>
      </filerInfo></headerData></edgarSubmission>"""
    client = _FakeClient({
        "index.json": _FakeResp(json_data={"directory": {"item": [
            {"name": "primary_doc.xml", "size": "2604"}]}}),
        "primary_doc.xml": _FakeResp(text=cover),
    })
    monkeypatch.setattr(funds, "_get_client", lambda: client)
    pos, period = funds._fetch_filing("0001423053", "000110465926104387")
    assert period == "2026-06-30"
    assert len(pos) == 1  # the table itself came from the cache
    saved = json.loads(path.read_text())
    assert saved["period"] == "2026-06-30"


def test_cik_padding():
    assert funds._cik10(1067983) == "0001067983"
    assert funds._cik10("1067983") == "0001067983"


def test_get_fund_lookup():
    assert funds.get_fund("berkshire")["name"] == "Berkshire Hathaway"
    assert funds.get_fund("nope") is None
    assert len(funds.FUNDS) >= 8


# ---------------------------------------------------------------------------
# Ask: multi-quarter history + the prompt-sized aggregate
# ---------------------------------------------------------------------------

def _fund(key, cik=0):
    return {"key": key, "name": f"Fund {key}", "manager": "Mgr",
             "cik": cik or {"alpha": 1001, "beta": 1002}.get(key, 2000)}


def _mk(issuer, value, cusip=""):
    return {"issuer": issuer, "class": "COM", "cusip": cusip,
            "value": value, "shares": 1.0}


def _wire(monkeypatch, tmp_path, subs, filings):
    """Point the two network-y helpers at canned data. `filings` maps
    dashless accession -> (positions, period)."""
    monkeypatch.setattr(funds, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(funds, "_submissions",
                        lambda cik10: subs[funds._cik10(cik10)[:0] + cik10])
    monkeypatch.setattr(funds, "_fetch_filing",
                        lambda cik10, a: filings[a])


def test_fund_history_dedupes_amended_quarters(monkeypatch, tmp_path):
    sub = _sub_with_13fs([
        ("13F-HR/A", "2026-08-20", "A-2"),   # restated Q2
        ("13F-HR",   "2026-08-14", "A-1"),   # original Q2
        ("13F-HR",   "2026-05-15", "B-1"),   # Q1
        ("13F-HR",   "2026-02-13", "C-1"),   # Q4 2025
    ])
    filings = {
        "A2": ([_mk("Apple", 2_000_000)], "2026-06-30"),
        "A1": ([_mk("Apple", 1_000_000)], "2026-06-30"),
        "B1": ([_mk("Apple", 800_000), _mk("Nvidia", 400_000)], "2026-03-31"),
        "C1": ([_mk("Nvidia", 1_000_000)], "2025-12-31"),
    }
    monkeypatch.setattr(funds, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(funds, "_submissions", lambda cik10: sub)
    monkeypatch.setattr(funds, "_fetch_filing", lambda cik10, a: filings[a])

    hist = funds.fund_history(_fund("alpha"), 3)
    assert [q["as_of"] for q in hist] == ["2026-06-30", "2026-03-31", "2025-12-31"]
    # the most recently *filed* version of Q2 (the amendment) wins
    assert hist[0]["form"] == "13F-HR/A"
    assert hist[0]["positions"][0]["value"] == 2_000_000
    assert hist[0]["total_value"] == 2_000_000


def test_fund_history_raises_when_no_filings(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(funds, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(funds, "_submissions",
                        lambda cik10: {"filings": {"recent": {
                            "form": ["13F-NT"], "filingDate": ["2026-08-01"],
                            "accessionNumber": ["X-1"]}}})
    with pytest.raises(RuntimeError):
        funds.fund_history(_fund("alpha"), 2)


def test_ask_data_single_quarter(monkeypatch, tmp_path):
    # alpha: Q1 [Apple, Meta] -> Q2 [Apple 5x, Nvidia, Zen]
    # beta:  Q1 [Nvidia, TSLA] -> Q2 [Nvidia 9x]
    filings = {
        "A2": ([_mk("Apple", 5e8), _mk("Nvidia", 2e8), _mk("Zen", 1e8)], "2026-06-30"),
        "A1": ([_mk("Apple", 1e8), _mk("Meta", 3e8)], "2026-03-31"),
        "B2": ([_mk("Nvidia", 9e8)], "2026-06-30"),
        "B1": ([_mk("Nvidia", 1e8), _mk("TSLA", 2e8)], "2026-03-31"),
    }
    subs = {
        "0000001001": _sub_with_13fs([("13F-HR", "2026-08-14", "A-2"),
                                       ("13F-HR", "2026-05-15", "A-1")]),
        "0000001002": _sub_with_13fs([("13F-HR", "2026-08-14", "B-2"),
                                       ("13F-HR", "2026-05-15", "B-1")]),
    }
    _wire(monkeypatch, tmp_path, subs, filings)

    data = funds.ask_data(quarters=1, roster=[_fund("alpha"), _fund("beta")])
    assert data["window"] == {"quarters": 1,
                              "start": "2026-06-30", "end": "2026-06-30"}
    assert [f["key"] for f in data["funds"]] == ["alpha", "beta"]

    qa = data["funds"][0]["quarters"][0]
    assert qa["total"] == 8e8 and qa["n"] == 3
    assert qa["top"][0] == {"name": "Apple", "usd": 5e8, "w": 62.5}

    added = {a["name"]: a for a in data["added"]}
    assert added["Nvidia"]["usd"] == 1e9        # +2e8 alpha, +8e8 beta
    assert added["Nvidia"]["funds"] == ["alpha", "beta"]
    assert added["Apple"]["usd"] == 4e8         # +4e8 alpha, flat in beta
    assert added["Apple"]["funds"] == ["alpha"]
    # held_now_usd accumulates across funds, not "last fund wins"
    assert added["Nvidia"]["held_now_usd"] == 1.1e9   # 2e8 alpha + 9e8 beta
    sold = {s["name"]: s for s in data["sold"]}
    assert sold["Meta"]["usd"] == -3e8 and sold["Meta"]["funds"] == ["alpha"]
    assert sold["TSLA"]["usd"] == -2e8 and sold["TSLA"]["funds"] == ["beta"]
    assert {b["name"] for b in data["brand_new"]} == {"Zen"}
    assert data["totals"] == {"added_usd": 1.5e9, "sold_usd": -5e8}
    assert data["missing"] == []


def test_ask_data_multi_quarter_window(monkeypatch, tmp_path):
    # Three distinct quarters per fund; asking for four uses what exists,
    # and moves are measured window start (oldest) vs window end (newest).
    filings = {
        "A2": ([_mk("Old", 1e8), _mk("Apple", 4e8), _mk("Nvidia", 3e8),
                _mk("Fresh", 1e8)], "2026-06-30"),
        "A1": ([_mk("Old", 2e8), _mk("Apple", 2e8), _mk("Nvidia", 1e8),
                _mk("Fresh", 1e8)], "2026-03-31"),
        "A0": ([_mk("Old", 5e8), _mk("Apple", 1e8)], "2025-12-31"),
        "B2": ([_mk("Nvidia", 5e8)], "2026-06-30"),
        "B1": ([_mk("Nvidia", 2e8)], "2026-03-31"),
        "B0": ([_mk("Nvidia", 1e8)], "2025-12-31"),
    }
    subs = {
        "0000001001": _sub_with_13fs([("13F-HR", "2026-08-14", "A-2"),
                                       ("13F-HR", "2026-05-15", "A-1"),
                                       ("13F-HR", "2026-02-13", "A-0")]),
        "0000001002": _sub_with_13fs([("13F-HR", "2026-08-14", "B-2"),
                                       ("13F-HR", "2026-05-15", "B-1"),
                                       ("13F-HR", "2026-02-13", "B-0")]),
    }
    _wire(monkeypatch, tmp_path, subs, filings)

    data = funds.ask_data(quarters=4, roster=[_fund("alpha"), _fund("beta")])
    assert data["window"]["quarters"] == 4
    assert data["window"]["start"] == "2025-12-31"
    assert data["window"]["end"] == "2026-06-30"
    assert [q["as_of"] for q in data["funds"][0]["quarters"]] == \
        ["2026-06-30", "2026-03-31", "2025-12-31"]

    added = {a["name"]: a for a in data["added"]}
    assert added["Nvidia"]["usd"] == 7e8        # +3e8 alpha, +4e8 beta
    assert added["Nvidia"]["funds"] == ["alpha", "beta"]
    assert added["Apple"]["usd"] == 3e8
    sold = {s["name"]: s for s in data["sold"]}
    assert sold["Old"]["usd"] == -4e8
    assert {b["name"] for b in data["brand_new"]} == {"Fresh"}


def test_ask_data_lists_unreadable_funds(monkeypatch, tmp_path):
    filings = {"A2": ([_mk("Apple", 1e8)], "2026-06-30"),
               "A1": ([_mk("Apple", 5e7)], "2026-03-31")}
    subs = {"0000001001": _sub_with_13fs([("13F-HR", "2026-08-14", "A-2"),
                                           ("13F-HR", "2026-05-15", "A-1")])}
    monkeypatch.setattr(funds, "CACHE_DIR", tmp_path)

    def _subs(cik10):
        if cik10 == funds._cik10(3003):
            raise RuntimeError("SEC: no such filer")
        return subs[cik10]

    monkeypatch.setattr(funds, "_submissions", _subs)
    monkeypatch.setattr(funds, "_fetch_filing", lambda cik10, a: filings[a])

    data = funds.ask_data(quarters=1,
                          roster=[_fund("alpha"), _fund("bad", cik=3003)])
    assert [f["key"] for f in data["funds"]] == ["alpha"]
    assert data["funds"][0]["name"] == "Fund alpha"
    assert data["missing"] == ["Fund bad"]
