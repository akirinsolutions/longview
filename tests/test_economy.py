"""Offline tests for the economy viewer.

The picture is static data — no prices, no network — so the tests are
about shape and arithmetic: seven levels, every branch ending on the
geography level, siblings adding to 100, beyond deriving from the stated
total, growth blending bottom-up, the saved-tree round trip, and the
plain-English 404s for bad addresses.
"""
import json

import pytest

from app import economy, vault


def _walk(node):
    yield node
    for c in node["children"]:
        yield from _walk(c)


ROOT = economy.view([])


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Keep every write inside the test: the tree's section of the vault
    file lives in the test's temp dir."""
    monkeypatch.setattr(vault, "VAULT_PATH", tmp_path / "longview.json")
    saved = economy._copy(economy._TREE)
    yield tmp_path
    economy._TREE = saved


def test_root_is_the_world():
    assert ROOT["level"] == 0
    assert ROOT["share"] == 100
    assert ROOT["path"] == []
    assert ROOT["value_usd"] == economy.TOTAL_USD
    assert [c["name"] for c in ROOT["children"]] == [
        "Real estate", "Cash & deposits", "Equities",
        "Insurance & pensions", "Bonds & loans", "Gold", "Crypto",
    ]


def test_meta_describes_the_picture():
    meta = economy.meta()
    assert meta["total_label"] == "$470T"
    assert meta["max_level"] == 7
    assert meta["horizons"] == list(economy.HORIZONS)
    assert meta["nodes"] >= 3000
    assert 4.0 <= meta["world_growth"] <= 5.5


def test_top_level_shares_sum_to_100():
    assert sum(c["share"] for c in ROOT["children"]) == 100


def test_every_sibling_set_sums_to_100():
    for node in _walk(ROOT):
        kids = node["children"]
        if kids:
            assert sum(c["share"] for c in kids) == 100, node["path"]


def test_every_branch_ends_on_geography():
    for node in _walk(ROOT):
        if not node["children"]:
            assert node["level"] == economy.MAX_LEVEL, node["path"]


def test_the_last_level_is_always_the_four_regions():
    for node in _walk(ROOT):
        if node["level"] == economy.MAX_LEVEL - 1:
            assert [c["name"] for c in node["children"]] == [
                "United States & Canada", "Europe", "China",
                "Asia-Pacific & rest",
            ], node["path"]
            assert sum(c["share"] for c in node["children"]) == 100


def test_the_tree_is_deep_and_wide():
    levels = {}
    for node in _walk(ROOT):
        levels[node["level"]] = levels.get(node["level"], 0) + 1
    assert sorted(levels) == list(range(8))
    assert levels[6] >= 400
    assert levels[7] >= 2000


def test_keys_are_slugs_and_unique_among_siblings():
    import re
    for node in _walk(ROOT):
        keys = [c["key"] for c in node["children"]]
        assert len(keys) == len(set(keys)), node["path"]
        for c in node["children"]:
            assert re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", c["key"]), c["key"]
            assert c["key"] == economy._slug(c["name"])


def test_fanout_is_two_to_five_except_the_world():
    for node in _walk(ROOT):
        kids = node["children"]
        if not kids:
            continue
        if node["level"] == 0:
            assert len(kids) == 7
        else:
            assert 2 <= len(kids) <= 5, node["path"]


def test_dollars_derive_from_the_parent():
    for node in _walk(ROOT):
        for c in node["children"]:
            expect = node["value_usd"] * c["share"] / 100
            assert c["value_usd"] == pytest.approx(expect)
            assert c["value_label"] == economy._fmt_usd(c["value_usd"])
            assert c["share_of_total"] == economy._share_of_total(c["value_usd"])


def test_every_node_carries_a_sane_growth_rate():
    for node in _walk(ROOT):
        assert isinstance(node["g"], (int, float))
        assert economy.MIN_GROWTH <= node["g"] <= economy.MAX_GROWTH


def test_growth_blends_bottom_up():
    for node in _walk(ROOT):
        kids = node["children"]
        if not kids:
            continue
        blend = sum(c["share"] * c["g"] for c in kids) / 100
        assert node["g"] == pytest.approx(blend, abs=0.06), node["path"]


def test_leaves_keep_their_own_growth_above_their_regions():
    """Geography adds a tilt, it does not flatten the asset's rate."""
    v = economy.view(["real_estate", "residential", "own_homes",
                      "family_houses", "detached_houses"])
    by_name = {c["name"]: c["g"] for c in v["children"]}
    assert by_name["Prime & waterfront"] > by_name["Affordable & rural"]


def test_paths_address_the_same_node():
    for node in _walk(ROOT):
        if node is ROOT or node["level"] > economy.MAX_LEVEL:
            continue
        got = economy.view(node["path"])
        assert got is not None
        assert got["name"] == node["name"]
        assert got["children"] == node["children"]


def test_a_deep_path_works_to_the_leaf():
    path = ["real_estate", "residential", "own_homes", "family_houses",
            "detached_houses", "prime_waterfront"]
    v = economy.view(path)
    assert v["name"] == "Prime & waterfront"
    assert v["level"] == 6
    assert [c["name"] for c in v["children"]] == [
        "United States & Canada", "Europe", "China", "Asia-Pacific & rest"]
    leaf = economy.view(path + ["united_states_canada"])
    assert leaf["level"] == 7
    assert leaf["children"] == []


def test_bad_addresses_are_none():
    assert economy.view(["nope"]) is None
    assert economy.view(["real_estate", "nope"]) is None
    # eight segments is one past the deepest addressable level
    assert economy.view(["a", "b", "c", "d", "e", "f", "g", "h"]) is None


def test_validate_tree_accepts_the_shipped_tree():
    assert economy.validate_tree(economy._TREE) == []


def test_projection_is_compound_arithmetic():
    assert economy.projected(100, 5, 10) == pytest.approx(162.889, abs=1e-3)
    assert economy.projected(100, 0, 20) == 100
    assert economy.projected(100, -2, 5) == pytest.approx(90.392, abs=1e-3)


@pytest.mark.parametrize("value, label", [
    (470e12, "$470T"),
    (244e12, "$244T"),
    (2.6e12, "$2.6T"),
    (430e9, "$430B"),
    (12e6, "$12M"),
    (1234, "$1,234"),
])
def test_fmt_usd(value, label):
    assert economy._fmt_usd(value) == label


def test_source_note_is_honest():
    assert "$470T" in economy.SOURCE_NOTE
    assert "UBS" in economy.SOURCE_NOTE
    assert "seven levels" in economy.SOURCE_NOTE
    assert "not live" in economy.SOURCE_NOTE


# ---------------------------------------------------------------------------
# What the model may change.
# ---------------------------------------------------------------------------

def _children(*rows):
    return [{"name": n, "share": s, "growth": g, "note": None}
            for n, s, g in rows]


def test_clean_children_normalises_shares():
    node = {"name": "Detached houses"}
    rows = economy.clean_children(
        _children(("A", 2, 5.0), ("B", 1, 4.0), ("C", 1, 3.0)), node)
    assert [r["share"] for r in rows] == [50, 25, 25]
    assert [r["growth"] for r in rows] == [5.0, 4.0, 3.0]


@pytest.mark.parametrize("rows", [
    _children(("Only", 100, 5.0)),
    _children(("A", 50, 5.0), ("A", 50, 5.0)),
    _children(("A", 50, 5.0), ("B", 50, 99.0)),
    _children(("A", 0, 5.0), ("B", 100, 5.0)),
    [{"name": "", "share": 50, "growth": 5.0},
     {"name": "B", "share": 50, "growth": 5.0}],
])
def test_clean_children_refuses_bad_lists(rows):
    with pytest.raises(RuntimeError):
        economy.clean_children(rows, {"name": "Parent"})


def test_clean_children_refuses_the_parents_name():
    with pytest.raises(RuntimeError):
        economy.clean_children(_children(("Parent", 50, 5.0),
                                         ("B", 50, 5.0)),
                               {"name": "Parent"})


def test_update_replaces_one_level_and_keeps_geography(sandbox):
    path = ["real_estate", "residential", "own_homes", "family_houses",
            "detached_houses"]
    before = economy.view(path)
    rows = economy.clean_children(
        _children(("Garden houses", 55, 5.2), ("Street houses", 45, 4.2)),
        before)
    out = economy.update(path, rows)
    assert out["children"] == ["Garden houses", "Street houses"]
    after = economy.view(path)
    assert [c["name"] for c in after["children"]] == out["children"]
    for c in after["children"]:
        assert [g["name"] for g in c["children"]] == [
            "United States & Canada", "Europe", "China",
            "Asia-Pacific & rest"]
    saved = json.loads((sandbox / "longview.json").read_text())[
        "sections"]["economy"]
    assert saved["tree"]["name"] == "Global household wealth"


def test_update_is_saved_and_reloaded(sandbox):
    path = ["cash_deposits", "bank_deposits", "everyday_accounts",
            "day_to_day_accounts", "checking_style_accounts"]
    rows = economy.clean_children(
        _children(("Personal accounts", 70, 3.1),
                  ("Business accounts", 30, 3.3)),
        economy.view(path))
    economy.update(path, rows)
    reloaded = economy._load()
    assert [c["name"] for c in reloaded["kids"]] == [
        "Real estate", "Cash & deposits", "Equities",
        "Insurance & pensions", "Bonds & loans", "Gold", "Crypto"]
    cash = reloaded["kids"][1]
    assert cash["kids"][0]["kids"][0]["kids"][0]["kids"][0]["kids"][0][
        "name"] == "Personal accounts"


def test_reset_restores_the_authored_tree(sandbox):
    path = ["real_estate", "residential", "own_homes", "family_houses",
            "detached_houses"]
    original = [c["name"] for c in economy.view(path)["children"]]
    rows = economy.clean_children(
        _children(("Garden houses", 50, 5.0), ("Street houses", 50, 4.0)),
        economy.view(path))
    economy.update(path, rows)
    assert [c["name"] for c in economy.view(path)["children"]] != original
    economy.reset()
    assert [c["name"] for c in economy.view(path)["children"]] == original
    # The reset drops the section: the authored tree is back, and the
    # vault holds no edited tree.
    assert vault.read_section("economy") is None


def test_update_only_works_on_the_sixth_level_list(sandbox):
    with pytest.raises(RuntimeError):
        economy.update(["real_estate"], [])


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------

def _client():
    from fastapi.testclient import TestClient
    import app.main as m
    return TestClient(m.app)


def test_routes():
    with _client() as client:
        r = client.get("/api/economy")
        assert r.status_code == 200
        body = r.json()
        assert body["level"] == 0
        assert len(body["children"]) == 7
        assert body["meta"]["max_level"] == 7

        r = client.get("/api/economy/real_estate/residential")
        assert r.status_code == 200
        assert r.json()["name"] == "Residential"

        r = client.get(
            "/api/economy/real_estate/residential/own_homes/family_houses/"
            "detached_houses/prime_waterfront/united_states_canada")
        assert r.status_code == 200
        assert r.json()["level"] == 7

        r = client.get("/api/economy/nope")
        assert r.status_code == 404

        r = client.get("/api/economy/a/b/c/d/e/f/g/h")
        assert r.status_code == 404
        assert "seven levels" in r.json()["detail"]


def test_update_needs_a_model(monkeypatch, sandbox):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)
    with _client() as client:
        r = client.post("/api/economy/update",
                        json={"path": ["real_estate", "residential",
                                       "own_homes", "family_houses",
                                       "detached_houses"]})
        assert r.status_code == 503
        assert "Settings" in r.json()["detail"]


def test_reset_route(sandbox):
    with _client() as client:
        r = client.post("/api/economy/reset")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["meta"]["max_level"] == 7


# ---------------------------------------------------------------------------
# The ten-year series (2015-2024) and comparison.
# ---------------------------------------------------------------------------

def test_world_series_is_the_report_record():
    from app import economy_series
    assert economy_series.YEARS == tuple(range(2015, 2025))
    w = economy_series.WORLD_BN
    assert len(w) == 10
    # 2023 and 2024 are the exact totals the editions state
    assert w[8] == 449965.0
    assert w[9] == 470508.0
    assert min(w) > 0
    assert max(w) == w[-1]  # the world still ends higher than any earlier year


def test_world_shape_anchored_at_2024():
    from app import economy_series
    s = economy_series.world_shape()
    assert len(s) == 10
    assert s[-1] == 1.0
    assert all(x > 0 for x in s)


def test_region_values_anchors_and_residual():
    from app import economy_series
    from app.economy_tree import REGION_NAMES
    vals = {n: economy_series.region_values(n) for n in REGION_NAMES}
    for n in REGION_NAMES:
        assert len(vals[n]) == 10
        assert all(x > 0 for x in vals[n])
    # the report's 2023 and 2024 anchors, verbatim
    assert vals["United States & Canada"][8] == 156999.0
    assert vals["United States & Canada"][9] == 174667.0
    assert vals["China"][8] == 97774.0
    assert vals["China"][9] == 100984.0
    # the residual keeps the four regions summing to the world, every year
    for i in range(10):
        total = sum(vals[n][i] for n in REGION_NAMES)
        assert abs(total - economy_series.WORLD_BN[i]) < 10


def test_region_shape_anchored():
    from app import economy_series
    from app.economy_tree import REGION_NAMES
    for n in REGION_NAMES:
        s = economy_series.region_shape(n)
        assert len(s) == 10
        assert s[-1] == 1.0


def test_node_values_take_the_right_shape():
    from app import economy_series
    # the world and its seven slices inherit the world's shape...
    v0 = economy_series.node_values("World", 0, 4700.0, 4.8)
    assert v0[-1] == pytest.approx(4700.0)
    v1 = economy_series.node_values("Real estate", 1, 1000.0, 0.0)
    assert v1[-1] == pytest.approx(1000.0)
    w = economy_series.WORLD_BN
    assert [a / v1[0] for a in v1] == pytest.approx(
        [x / w[0] for x in w], rel=1e-3)
    # ...a geography leaf inherits its region's shape...
    v7 = economy_series.node_values("China", 7, 500.0, 0.0)
    shape = economy_series.region_shape("China")
    assert v7 == pytest.approx([500.0 * s for s in shape], rel=1e-3)
    # ...and everything in between walks back at its own growth rate
    v3 = economy_series.node_values("X", 3, 100.0, 6.0)
    assert v3[-1] == pytest.approx(100.0)
    assert v3[0] == pytest.approx(100.0 / 1.06 ** 9, rel=1e-3)


def test_series_payload_shape():
    from app import economy_series
    from app.economy_tree import REGION_NAMES
    p = economy_series.series_payload()
    assert p["years"] == list(range(2015, 2025))
    assert p["last_year"] == 2024
    assert len(p["world"]) == 10
    assert set(p["regions"]) == set(REGION_NAMES)
    assert all(len(r) == 10 for r in p["regions"].values())


def test_meta_carries_the_series():
    m = economy.meta()
    assert m["series"]["last_year"] == 2024
    assert m["series"]["world"][-1] == 470508.0
    assert "56 markets" in m["series_note"]


def test_compare_needs_something():
    with pytest.raises(RuntimeError):
        economy.compare([])
    with pytest.raises(RuntimeError):
        economy.compare([[], ""])


def test_compare_rejects_unknown_paths():
    with pytest.raises(RuntimeError) as ei:
        economy.compare(["nope"])
    assert "not in the tree" in str(ei.value)


def test_compare_dedupes_and_caps_at_five():
    out = economy.compare(["real_estate", "real_estate"])
    assert len(out["series"]) == 1
    with pytest.raises(RuntimeError):
        economy.compare(["a", "b", "c", "d", "e", "f"])


def test_compare_series_match_the_view():
    out = economy.compare(["real_estate", "real_estate/residential"])
    assert len(out["series"]) == 2
    for s in out["series"]:
        assert len(s["values_bn"]) == 10
        assert s["values_bn"][-1] > 0
        assert s["basis"]
    assert out["years"] == list(range(2015, 2025))
    # same node addressed three ways: one line, and the same 2024 value
    out = economy.compare(
        ["real_estate", ["real_estate"], "real_estate/residential"])
    assert len(out["series"]) == 2
    a = out["series"][0]["value_2024_usd"]
    assert a == pytest.approx(
        economy.view(["real_estate"])["value_usd"])


def test_ai_compare_without_a_model(monkeypatch):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)
    with pytest.raises(RuntimeError):
        economy.ai_compare(["real_estate"])


def test_compare_route():
    with _client() as client:
        r = client.post("/api/economy/compare",
                        json={"paths": ["real_estate", "cash_deposits"],
                              "ai": False})
        assert r.status_code == 200
        body = r.json()
        assert body["years"][0] == 2015 and body["years"][-1] == 2024
        assert [s["name"] for s in body["series"]] == \
            ["Real estate", "Cash & deposits"]


def test_compare_route_plain_english_errors():
    with _client() as client:
        r = client.post("/api/economy/compare", json={"paths": ["nope"]})
        assert r.status_code == 400
        assert "not in the tree" in r.json()["detail"]
        r = client.post("/api/economy/compare", json={"paths": ["a"] * 6})
        assert r.status_code == 400
        assert "five" in r.json()["detail"]


def test_compare_route_ai_needs_a_model(monkeypatch):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)
    with _client() as client:
        r = client.post("/api/economy/compare",
                        json={"paths": ["real_estate"], "ai": True})
        assert r.status_code == 503
        assert "Settings" in r.json()["detail"]


def test_compare_route_ai_with_model(monkeypatch):
    import app.risk as risk
    monkeypatch.setenv("PROOF_LLM_KEY", "k")
    monkeypatch.setattr(
        risk, "_post_llm",
        lambda system, user, max_tokens=4000, timeout=60:
        ("Here is a read.", "stub-model"))
    with _client() as client:
        r = client.post("/api/economy/compare",
                        json={"paths": ["real_estate", "equities"], "ai": True})
        assert r.status_code == 200
        body = r.json()
        assert body["ai"] == "Here is a read."
        assert body["model"] == "stub-model"
        assert len(body["series"]) == 2
