"""The scan query: filters, sorting, and the aggregate view (no network)."""
from app import funds


def _row(fund, issuer, cusip, value, prev, status, **kw):
    """A synthetic pool row shaped like what funds._enrich_row produces."""
    r = {
        "fund": fund, "fund_name": fund.title(),
        "issuer": issuer, "class": "COM", "cusip": cusip,
        "key": f"CU {cusip}", "value": value, "shares": value / 10,
        "weight": 0.1, "asset": "stock", "prev_value": prev,
        "change": (value / prev - 1.0) if prev else None,
        "move_value": value - (prev or 0.0),
        "status": status, "n_funds": 1, "holders": [fund],
        "surprise": False,
    }
    r.update(kw)
    return r


def _pool(rows):
    return {"v": 2, "roster": "r", "generated": 0, "as_of": "2026-06-30",
            "funds": [], "rows": rows, "new_this_quarter": [],
            "biggest_moves": [], "crowding_change": []}


def test_aggregate_dedupes_same_cusip_held_by_three_funds():
    pool = _pool([
        _row("berkshire", "APPLE INC", "037833100", 1e9, 8e8, "increased"),
        _row("tiger", "APPLE INC", "037833100", 2e9, 2e9, "unchanged"),
        _row("citadel", "Apple Inc", "037833100", 5e8, 5e8, "unchanged"),
    ])
    d = funds.scan_query(pool, {"aggregate": "1"})
    assert d["total"] == 1 and d["shown"] == 1
    a = d["rows"][0]
    assert a["value"] == 3.5e9                       # summed across funds
    assert a["n_funds"] == 3
    assert a["holders"] == ["berkshire", "citadel", "tiger"]
    assert a["issuer"] == "APPLE INC"                # most common spelling
    assert a["fund"] == "tiger"                      # biggest holder stands in
    assert a["cusip"] == "037833100"


def test_no_aggregate_keeps_one_row_per_position():
    pool = _pool([
        _row("berkshire", "APPLE INC", "037833100", 1e9, 8e8, "increased"),
        _row("tiger", "APPLE INC", "037833100", 2e9, 2e9, "unchanged"),
    ])
    assert funds.scan_query(pool, {})["total"] == 2
    assert funds.scan_query(pool, {"aggregate": "1"})["total"] == 1


def test_aggregate_worth_and_change_are_sums():
    pool = _pool([
        _row("a", "X Corp", "1", 1e9, 8e8, "increased"),
        _row("b", "X Corp", "1", 2e9, 2e9, "unchanged"),
    ])
    x = funds.scan_query(pool, {"aggregate": "1"})["rows"][0]
    assert x["value"] == 3e9 and x["prev_value"] == 2.8e9
    assert abs(x["change"] - (3e9 / 2.8e9 - 1.0)) < 1e-12
    assert x["status"] == "increased"
    assert x["move_value"] == 2e8                    # +0.2 + 0.0


def test_aggregate_status_all_new():
    pool = _pool([
        _row("a", "X Corp", "1", 5e7, None, "new"),
        _row("b", "X Corp", "1", 1e8, None, "new"),
    ])
    x = funds.scan_query(pool, {"aggregate": "1"})["rows"][0]
    assert x["status"] == "new" and x["change"] is None
    assert x["value"] == 1.5e8


def test_aggregate_status_all_exited():
    pool = _pool([
        _row("a", "X Corp", "1", 0.0, 5e8, "exited"),
        _row("b", "X Corp", "1", 0.0, 2e8, "exited"),
    ])
    x = funds.scan_query(pool, {"aggregate": "1"})["rows"][0]
    assert x["status"] == "exited"
    assert x["value"] == 0.0 and x["prev_value"] == 7e8
    assert x["n_funds"] == 2                         # who held it counts too


def test_aggregate_status_mixed_uses_net_move():
    pool = _pool([
        _row("a", "X Corp", "1", 1.02, 1.0, "increased"),
        _row("b", "X Corp", "1", 1.9, 2.0, "decreased"),
    ])
    x = funds.scan_query(pool, {"aggregate": "1"})["rows"][0]
    # net 2.92 vs 3.00 -> down 2.7% -> "decreased"
    assert x["status"] == "decreased"
    pool = _pool([
        _row("a", "X Corp", "1", 1.0, 1.0, "unchanged"),
        _row("b", "X Corp", "1", 1.99, 2.0, "unchanged"),
    ])
    assert funds.scan_query(pool, {"aggregate": "1"})["rows"][0]["status"] == \
        "unchanged"                                  # net within 0.5%


def test_aggregate_surprise_only_when_sole_new_holder():
    pool = _pool([_row("a", "X Corp", "1", 5e7, None, "new")])
    assert funds.scan_query(pool, {"aggregate": "1"})["rows"][0]["surprise"]
    pool = _pool([
        _row("a", "X Corp", "1", 5e7, None, "new"),
        _row("b", "X Corp", "1", 1e8, None, "new"),
    ])
    assert not funds.scan_query(pool, {"aggregate": "1"})["rows"][0]["surprise"]


def test_aggregate_filters_apply_per_position_first():
    pool = _pool([
        _row("berkshire", "Apple Inc", "037833100", 1e9, 8e8, "increased"),
        _row("tiger", "Apple Inc", "037833100", 2e9, 2e9, "unchanged"),
        _row("tiger", "Microsoft", "594918104", 5e8, None, "new"),
    ])
    d = funds.scan_query(pool, {"aggregate": "1", "q": "apple"})
    assert d["total"] == 1 and d["rows"][0]["value"] == 3e9
    d = funds.scan_query(pool, {"aggregate": "1", "funds": "berkshire"})
    assert d["total"] == 1 and d["rows"][0]["value"] == 1e9
    d = funds.scan_query(pool, {"aggregate": "1", "min_value": "1500000000"})
    # min_value filters *positions* first: the $1B slice drops, the company
    # then shows the remaining $2B, not the unfiltered $3B.
    assert d["total"] == 1 and d["rows"][0]["value"] == 2e9
    assert d["rows"][0]["n_funds"] == 1


def test_aggregate_limit_counts_companies():
    rows = [_row(f"f{i}", f"C{i} Corp", f"cusip{i}", 1e8 * (i + 1), None, "new")
            for i in range(5)]
    rows += [_row("f9", "C3 Corp", "cusip3", 9e7, None, "new")]  # 6 positions, 5 companies
    d = funds.scan_query(_pool(rows), {"aggregate": "1", "limit": "2"})
    assert d["total"] == 5 and d["shown"] == 2 and len(d["rows"]) == 2


def test_aggregate_sorts_by_summed_worth():
    pool = _pool([
        _row("a", "Small Corp", "1", 1e7, 1e7, "unchanged"),
        _row("b", "Small Corp", "1", 1e7, 1e7, "unchanged"),
        _row("a", "Big Corp", "2", 9e8, 9e8, "unchanged"),
    ])
    d = funds.scan_query(pool, {"aggregate": "1", "sort": "value", "dir": "desc"})
    assert [r["issuer"] for r in d["rows"]] == ["Big Corp", "Small Corp"]
    d = funds.scan_query(pool, {"aggregate": "1", "sort": "value", "dir": "asc"})
    assert [r["issuer"] for r in d["rows"]] == ["Small Corp", "Big Corp"]


def test_aggregate_breakdown_sums_to_total_and_orders():
    pool = _pool([
        _row("berkshire", "Apple Inc", "037833100", 1e9, 8e8, "increased"),
        _row("tiger", "Apple Inc", "037833100", 2e9, 2e9, "unchanged"),
        _row("icahn", "Apple Inc", "037833100", 5e8, 6e8, "decreased"),
    ])
    a = funds.scan_query(pool, {"aggregate": "1"})["rows"][0]
    assert abs(sum(b["value"] for b in a["breakdown"]) - a["value"]) < 1e-6
    assert [b["fund"] for b in a["breakdown"]] == ["tiger", "berkshire", "icahn"]


def test_aggregate_flag_forms():
    pool = _pool([
        _row("a", "X Corp", "1", 1e9, 1e9, "unchanged"),
        _row("b", "X Corp", "1", 2e9, 2e9, "unchanged"),
    ])
    for on in ("1", "true", "yes"):
        assert funds.scan_query(pool, {"aggregate": on})["total"] == 1
    for off in ("0", "false", ""):
        assert funds.scan_query(pool, {"aggregate": off})["total"] == 2


def test_aggregate_groups_on_name_when_no_cusip():
    r1 = _row("a", "ALLY FINL INC", "", 1e8, 1e8, "unchanged")
    r2 = _row("b", "ALLY FINL, INC.", "", 2e8, 2e8, "unchanged")
    del r1["key"]
    del r2["key"]
    d = funds.scan_query(_pool([r1, r2]), {"aggregate": "1"})
    assert d["total"] == 1                            # same normalized name
    assert d["rows"][0]["value"] == 3e8


def test_csv_handles_aggregate_rows():
    pool = _pool([
        _row("a", "X Corp", "1", 1e9, 8e8, "increased"),
        _row("b", "X Corp", "1", 2e9, 2e9, "unchanged"),
    ])
    text = funds.rows_to_csv(funds.scan_query(pool, {"aggregate": "1"})["rows"])
    lines = text.strip().splitlines()
    assert len(lines) == 2                                  # header + one company
    cols = lines[1].split(",")
    assert cols[0] == "b"            # the bigger holder stands for the company
    assert cols[6] == "3000000000"   # summed value
    assert cols[8] == ""             # a % of *which* fund? left blank
    assert cols[12] == "2" and cols[13] == "a;b"
