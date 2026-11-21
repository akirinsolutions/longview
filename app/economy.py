"""Economy viewer: where the world's wealth is held.

A static, global reference picture — about $470 trillion of end-2024
global household wealth, from the tree in ``economy_tree``. Seven
levels deep: six authored levels of detail, then geography (where in
the world that slice sits). Every node shows its share of its parent
(whole percentages), the dollar amount that share works out to, and a
nominal annual growth rate.

Nothing here is live: no prices, no quotes, no sources fetched at
request time. The tree is authored data plus arithmetic on a stated
total. Growth rates are assumptions a reader can move; the AI route can
rewrite one level's list and save it to ``data/economy_tree.json``.

Addressing is by path: ``real_estate/residential/own_homes/...`` — a
slash-joined chain of node keys. ``view(path)`` returns the node at
that path with its full remaining subtree, or None when any segment is
unknown or the path runs past the seventh level.

The meta carries the ten-year shapes (2015–2024) every chart is built
from — ``economy_series``; ``compare()`` gives up to five nodes their
histories, and ``ai_compare()`` adds the model's read of them.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone

from . import economy_series, vault
from .economy_tree import (REGION_NAMES, REGION_SHARES, REGION_GROWTH,
                           TREE, WORLD_GROWTH, _blend)

# The stated total the whole picture is built from (USD, end-2024, rounded).
# UBS Global Wealth Report 2025: global personal wealth ≈ $470.5T.
TOTAL_USD = 470e12
TOTAL_LABEL = "$470T"

SOURCE_NOTE = (
    "A rounded reference picture of global household wealth at the end "
    "of 2024 — about $470T, per the UBS Global Wealth Report 2025, "
    "seven levels deep. Branch splits follow OECD/ECB household-wealth "
    "data, the WTW Global Pension Assets Study, and sector sources for "
    "gold, crypto, and listed markets; the last level is geography. "
    "Growth rates are nominal USD assumptions built on the published "
    "long-run record (3.4%/yr real since 2000, ~5%/yr projected), not "
    "forecasts. Whole percentages; dollars derived from the $470T "
    "total. Static — not live data, not accounting."
)

SERIES_NOTE = (
    "The ten-year charts read 2015 to 2024 from the UBS Global Wealth "
    "Reports. The world's line is the report's own record — 2023 and 2024 "
    "the exact edition totals, the earlier points taken from the report's "
    "chart (±0.1-0.5k bn), and 2022 resting on a different source per the "
    "report. The four regions are anchored on the report's 2023 and 2024 "
    "tables and walked back at the since-2008 growth the reports state for "
    "each; 'Asia-Pacific & rest' is the world minus the other three, so "
    "they always add up to the world. The seven top slices inherit the "
    "world's shape with flat shares, and everything deeper is walked back "
    "at the node's own growth rate — those two are assumptions, not "
    "records. The report's 56 markets cover nearly all of the world's "
    "wealth, but the charts are the sample's history, not every household."
)

# Levels: 0 is the root, 1-6 are authored, 7 is geography.
MAX_LEVEL = 7
LEVEL_NAMES = (
    "the whole picture", "the seven big slices", "the second level",
    "the third level", "the fourth level", "the fifth level",
    "the sixth level", "where in the world",
)

# Horizons the page offers for growth projections, in years.
HORIZONS = (5, 10, 15, 20)

# Grown-up bounds for a rate a reader or a model can set (nominal %/yr).
MIN_GROWTH = -5.0
MAX_GROWTH = 25.0

_SECTION = "economy"

_LOCK = threading.Lock()


def _slug(name: str) -> str:
    """The URL-safe key a node is addressed by: its name, slugged."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _fmt_usd(v: float) -> str:
    """$260T / $2.6T / $430B / $12M / $840 — small enough for a chart label."""
    if v >= 1e12:
        t = v / 1e12
        return f"${t:.0f}T" if t >= 9.95 else f"${t:.1f}T"
    if v >= 1e9:
        return f"${v / 1e9:.0f}B"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:,.0f}"


def _share_of_total(value: float) -> float:
    """The node's slice of the whole pie, as a percentage (rounded to
    one decimal when >= 1, two below)."""
    x = value / TOTAL_USD * 100
    return round(x, 1) if x >= 1 else round(x, 2)


def projected(value: float, growth: float, years: int) -> float:
    """What a value becomes at a constant nominal rate. The page's only
    forecast: compound arithmetic on a rate the reader can see and move."""
    return value * (1 + growth / 100) ** years


# ---------------------------------------------------------------------------
# The live tree: the authored one, plus any saved AI edits.
# ---------------------------------------------------------------------------

def _copy(tree: dict) -> dict:
    """A deep-enough copy: the stored trees are plain JSON."""
    return json.loads(json.dumps(tree))


def _new_leaf(name: str, share: float, growth: float,
              note: str | None = None) -> dict:
    return {"name": name, "share": share, "note": note, "g": growth,
            "regions": None, "rg": None, "kids": []}


def validate_tree(node: dict, level: int = 0,
                  path: tuple[str, ...] = ()) -> list[str]:
    """Check every invariant the page relies on. Returns a list of
    plain-English problems — empty means the tree is shippable."""
    problems: list[str] = []
    here = path + (str(node.get("name", "?")),)
    kids = node.get("kids") or []
    growth = node.get("g")

    if not isinstance(growth, (int, float)):
        problems.append("no growth rate at " + " / ".join(here))
    elif not (MIN_GROWTH <= float(growth) <= MAX_GROWTH):
        problems.append(f"growth {growth} out of range at " + " / ".join(here))

    if kids:
        if level >= MAX_LEVEL:
            problems.append("too deep at " + " / ".join(here))
            return problems
        total = sum(float(k.get("share") or 0) for k in kids)
        if abs(total - 100) > 0.51:
            problems.append(f"shares sum to {total:g} at " + " / ".join(here))
        limit = 8 if level == 0 else 5
        if not (2 <= len(kids) <= limit):
            problems.append(f"{len(kids)} children at " + " / ".join(here))
        keys = [_slug(str(k.get("name", ""))) for k in kids]
        if len(keys) != len(set(keys)) or "" in keys:
            problems.append("repeated or empty name at " + " / ".join(here))
        for k in kids:
            problems.extend(validate_tree(k, level + 1, here))
    elif level != MAX_LEVEL:
        problems.append(f"branch stops at level {level}: " + " / ".join(here))
    return problems


def _load() -> dict:
    """The saved tree when it is whole, else the authored one."""
    raw = vault.read_section(_SECTION)
    if raw is not None:
        try:
            tree = raw.get("tree") if isinstance(raw, dict) else raw
            if isinstance(tree, dict) and not validate_tree(tree):
                return tree
        except (ValueError, TypeError):
            pass
    return _copy(TREE)


_TREE = _load()


def _save(tree: dict) -> None:
    """Write the edited tree to the vault; the write is atomic, so a
    failed write changes nothing."""
    body = {"version": 1,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tree": tree}
    vault.write_section(_SECTION, body)


def _authored() -> dict:
    return _copy(TREE)


# ---------------------------------------------------------------------------
# The view: shares, dollars, growth, subtree.
# ---------------------------------------------------------------------------

def _view_node(node: dict, parent_value: float, level: int,
               path: list[str]) -> dict:
    """One raw tree node -> the shape the page shows, subtree included."""
    key = _slug(node["name"])
    value = parent_value * node["share"] / 100
    children = [
        _view_node(c, value, level + 1, path + [_slug(c["name"])])
        for c in node["kids"]
    ]
    return {
        "name": node["name"],
        "key": key,
        "note": node.get("note") or "",
        "share": node["share"],
        "value_usd": value,
        "value_label": _fmt_usd(value),
        "share_of_total": _share_of_total(value),
        "g": round(float(node.get("g") or 0), 1),
        "level": level,
        "path": path,
        "n_subs": len(children),
        "children": children,
    }


def _locate(path: list[str]):
    """Walk the tree down ``path``. Returns (node, value, parent_value)
    — the value of the node itself and of its parent (the stated total
    for a level-1 node) — or None."""
    node = _TREE
    value = TOTAL_USD
    parent_value = None
    for seg in path:
        nxt = None
        for c in node["kids"]:
            if _slug(c["name"]) == seg:
                nxt = c
                break
        if nxt is None:
            return None
        parent_value, value = value, value * nxt["share"] / 100
        node = nxt
    return node, value, parent_value


def view(path: list[str] | None = None) -> dict | None:
    """One node of the tree as the page shows it, subtree included.

    An empty path is the top: the whole of global household wealth and
    its seven slices. Any unknown segment, or a path past the seventh
    level, is None so the route can 404 in plain English.
    """
    path = [p for p in (path or []) if p]
    if len(path) > MAX_LEVEL:
        return None
    found = _locate(path)
    if found is None:
        return None
    node, value, parent_value = found
    return {
        "name": node["name"],
        "key": _slug(node["name"]) if path else None,
        "note": node.get("note") or "",
        "share": node["share"],
        "value_usd": value,
        "value_label": _fmt_usd(value),
        "share_of_total": _share_of_total(value),
        "g": round(float(node.get("g") or 0), 1),
        "level": len(path),
        "path": path,
        "n_subs": len(node["kids"]),
        "children": [
            _view_node(c, value, len(path) + 1, path + [_slug(c["name"])])
            for c in node["kids"]
        ],
    }


def node_count(v: dict | None = None) -> int:
    """How many nodes the picture holds (root included)."""
    if v is None:
        v = view([])

    def count(node: dict) -> int:
        return 1 + sum(count(c) for c in node["children"])

    return count(v)


def meta() -> dict:
    """The numbers the page header and strip need."""
    root = view([])
    return {
        "total_usd": TOTAL_USD,
        "total_label": TOTAL_LABEL,
        "source_note": SOURCE_NOTE,
        "world_growth": round(float(_TREE.get("g") or WORLD_GROWTH), 1),
        "horizons": list(HORIZONS),
        "max_level": MAX_LEVEL,
        "max_path": MAX_LEVEL,
        "nodes": node_count(root),
        "regions": list(REGION_NAMES),
        "series": economy_series.series_payload(),
        "series_note": SERIES_NOTE,
        "edited": vault.read_section(_SECTION) is not None,
        "updated": _updated_at(),
    }


def _updated_at() -> str | None:
    raw = vault.read_section(_SECTION)
    if raw is None:
        return None
    return raw.get("updated") if isinstance(raw, dict) else None


# ---------------------------------------------------------------------------
# Editing: manual reset, AI rewrite of one level.
# ---------------------------------------------------------------------------

def reset() -> dict:
    """Forget saved AI edits and go back to the authored tree."""
    global _TREE
    with _LOCK:
        _TREE = _authored()
        vault.write_section(_SECTION, None)
    return meta()


def _profile(node: dict, path: list[str]):
    """The effective geography split for a branch: the nearest override.

    Walks down the path so an AI-rewritten level keeps the region mix
    its branch was authored with.
    """
    names, shares, growth = REGION_NAMES, REGION_SHARES, REGION_GROWTH
    walk = _TREE
    for seg in path:
        if walk.get("regions") is not None:
            shares = tuple(walk["regions"])
        if walk.get("rg") is not None:
            growth = tuple(walk["rg"])
        for c in walk["kids"]:
            if _slug(c["name"]) == seg:
                walk = c
                break
        else:
            return names, shares, growth
    if walk.get("regions") is not None:
        shares = tuple(walk["regions"])
    if walk.get("rg") is not None:
        growth = tuple(walk["rg"])
    return names, shares, growth


def _geography(path: list[str]) -> list[dict]:
    names, shares, growth = _profile(_TREE, path)
    return [_new_leaf(nm, sh, gr) for nm, sh, gr in zip(names, shares, growth)
            if sh > 0]


def _whole_percent(shares: list[float]) -> list[int]:
    """Round shares to whole percentages that still add up to 100."""
    total = sum(shares) or 1.0
    exact = [s * 100 / total for s in shares]
    out = [int(x) for x in exact]
    short = 100 - sum(out)
    order = sorted(range(len(exact)), key=lambda i: exact[i] - out[i],
                   reverse=True)
    for i in order[:short]:
        out[i] += 1
    return out


def clean_children(raw, existing: dict) -> list[dict]:
    """Validate what the model proposed and turn it into tree nodes.

    Strict on purpose: a malformed answer changes nothing. Raises
    ``RuntimeError`` in plain English; the route turns that into a 502.
    """
    if not isinstance(raw, list):
        raise RuntimeError("the model did not return a list of children")
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or len(name) > 60:
            continue
        try:
            share = float(item.get("share"))
            growth = float(item.get("growth", item.get("g")))
        except (TypeError, ValueError):
            continue
        if not (0 < share <= 100):
            continue
        if not (MIN_GROWTH <= growth <= MAX_GROWTH):
            continue
        note = item.get("note")
        note = " ".join(str(note).split())[:160] if note else None
        rows.append({"name": name, "share": share,
                     "growth": round(growth, 1), "note": note})
    if not (2 <= len(rows) <= 5):
        raise RuntimeError("the model's list was not 2 to 5 usable children")
    if len({_slug(r["name"]) for r in rows}) != len(rows):
        raise RuntimeError("the model repeated a name in its list")
    if any(_slug(r["name"]) == _slug(existing["name"]) for r in rows):
        raise RuntimeError("the model reused the parent's own name")
    whole = _whole_percent([r["share"] for r in rows])
    for row, share in zip(rows, whole):
        row["share"] = share
    return rows


def update(path: list[str], children: list[dict]) -> dict:
    """Replace one level-5 node's list with validated children.

    Level 5 is the last authored level, so the new children sit at
    level 6 and keep the branch's geography at level 7. The edit is
    saved atomically.
    """
    global _TREE
    path = [p for p in (path or []) if p]
    if len(path) != 5:
        raise RuntimeError("AI updates work on the sixth level list — "
                           "open a branch five levels down first")
    found = _locate(path)
    if found is None:
        raise RuntimeError("that part of the tree is not there")
    node, _, _ = found
    with _LOCK:
        kids = []
        for row in children:
            kid = _new_leaf(row["name"], row["share"], row["growth"],
                            row["note"])
            kid["kids"] = _geography(path)
            kids.append(kid)
        node["kids"] = kids
        _blend(_TREE)
        _save(_TREE)
    return {"children": [k["name"] for k in kids],
            "names": [k["name"] for k in kids],
            "meta": meta(),
            "view": view(path)}


_UPDATE_SYSTEM = """You are extending a reference tree of global household wealth.

Each node splits one category into 2-5 children whose shares of the parent add up to 100.
The tree is six authored levels of detail plus a seventh level that is always geography
(United States & Canada, Europe, China, Asia-Pacific & rest), which is added for you.

Given one node, propose 2-5 replacement children that split it by a real, observable
dimension at the next level down. Be specific and factual: name real sub-kinds, not
"Other" or "Miscellaneous". Keep names under 45 characters. Give each child:
  "name": short plain-English name
  "share": percentage of the parent, a number; the shares must add up to 100
  "growth": nominal USD growth per year, a number between 0 and 20
  "note": one short plain-English line, or null

Growth should follow the long-run record: global household wealth about 4-5%/yr nominal,
cash about 3%, bonds about 4%, equities about 7%, gold about 5%, crypto high but volatile.
Answer with JSON only: {"children": [{"name": ..., "share": ..., "growth": ..., "note": ...}]}
"""


def ai_update(path: list[str]) -> dict:
    """Ask the configured model for a better child list, then validate it.

    Nothing is saved when the answer is unusable. Raises RuntimeError in
    plain English; the route maps that to 502 and a missing key to 503.
    """
    from . import risk  # the shared llm seam (request key or environment)

    path = [p for p in (path or []) if p]
    if len(path) != 5:
        raise RuntimeError("AI updates work on the sixth level list — "
                           "open a branch five levels down first")
    found = _locate(path)
    if found is None:
        raise RuntimeError("that part of the tree is not there")
    node, value, _ = found
    brief = {
        "path": path,
        "node": node["name"],
        "share_of_parent": node["share"],
        "dollars": _fmt_usd(value * node["share"] / 100),
        "current_children": [k["name"] for k in node["kids"]],
        "world_growth": WORLD_GROWTH,
    }
    content, model = risk._post_llm(
        _UPDATE_SYSTEM,
        "Node: " + json.dumps(brief, separators=(",", ":")),
    )
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise RuntimeError("the model did not return a usable list")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise RuntimeError("the model's list was not valid JSON")
    rows = clean_children(data.get("children") if isinstance(data, dict)
                          else data, node)
    out = update(path, rows)
    out["model"] = model
    return out


# ---------------------------------------------------------------------------
# Comparison: up to five nodes, ten years each, optionally read by the model.
# ---------------------------------------------------------------------------

def _basis(level: int, name: str) -> str:
    """Plain-English label for how honest the node's history is."""
    if level == 0:
        return "the world's own record, 2015-2024 (UBS Global Wealth Report)"
    if level == 1:
        return "assumed: the world's shape with a flat share back to 2015"
    if level == MAX_LEVEL:
        return ("geography: " + name + "'s measured record where the reports "
                "publish it, modelled in between")
    return "assumed: walked back at the node's own growth rate"


def compare(paths: list) -> dict:
    """Up to five nodes, each with its ten-year history, ready to chart.

    The page does this same arithmetic locally for its own charts; the
    route exists so the model can compare on the server. A path that is
    not in the tree, or more than five picks, is a RuntimeError in
    plain English; the route turns those into a 400.
    """
    picks = []
    for p in paths or []:
        if isinstance(p, str):
            p = [s for s in p.split("/") if s]
        elif isinstance(p, (list, tuple)):
            p = [str(s) for s in p if str(s)]
        else:
            continue
        if p:
            picks.append(p)
    if not picks:
        raise RuntimeError("nothing to compare — pick at least one thing")
    if len(picks) > 5:
        raise RuntimeError("a comparison holds at most five things")
    series = []
    seen = set()
    for p in picks:
        if len(p) > MAX_LEVEL:
            raise RuntimeError("one of those is one past the bottom of the tree")
        v = view(p)
        if v is None:
            raise RuntimeError("one of those is not in the tree: "
                               + "/".join(p))
        sig = "/".join(v["path"])
        if sig in seen:  # the same thing twice is one line, not two
            continue
        seen.add(sig)
        series.append({
            "name": v["name"],
            "path": v["path"],
            "level": v["level"],
            "level_name": LEVEL_NAMES[v["level"]],
            "share_of_total_pct": v["share_of_total"],
            "value_2024_usd": v["value_usd"],
            "value_2024_label": v["value_label"],
            "growth_pct": v["g"],
            "values_bn": list(economy_series.node_values(
                v["name"], v["level"], v["value_usd"] / 1e9, v["g"])),
            "basis": _basis(v["level"], v["name"]),
        })
    return {"years": list(economy_series.YEARS), "series": series}


_COMPARE_SYSTEM = """You are comparing slices of a reference picture of global household wealth (end 2024, about $470 trillion, UBS Global Wealth Report).

You are given a few slices, each with its 2015-2024 history in USD billions, its share of the whole, and how its history was built (measured or assumed).

Write a short plain-English comparison of under 250 words: what each slice is, how their ten-year paths differ or agree, what their shares say about where the wealth actually sits, and one or two caveats about the assumed parts of the histories. Plain prose, no investment advice, no jargon. Answer in plain text only.
"""


def ai_compare(paths: list) -> dict:
    """The comparison plus the model's read of it.

    The model sees the same series the chart draws, recomputed here from
    the live tree and the report's shapes. Raises RuntimeError in plain
    English; the route maps a missing key to 503 and other failures to
    502, and the page falls back to the chart without the commentary.
    """
    from . import risk  # the shared llm seam (request key or environment)

    out = compare(paths)
    brief = {
        "what": ("slices of a reference picture of global household wealth, "
                 "end 2024, about $470T (UBS Global Wealth Report 2025)"),
        "world_bn": {"years": out["years"],
                     "values": list(economy_series.WORLD_BN)},
        "slices": out["series"],
    }
    # A thinking model spends the whole token budget on reasoning before
    # it writes a word. Measured on the local model: five slices think
    # ~7,400 tokens and then write ~1,700, so the default 4,000 budget
    # comes back with an empty answer. Give the read room to happen, and
    # a longer clock to spend it.
    content, model = risk._post_llm(
        _COMPARE_SYSTEM,
        "Data: " + json.dumps(brief, separators=(",", ":")),
        max_tokens=8000,
        timeout=180,
    )
    if not content.strip():
        raise RuntimeError("the model ran out of room to answer — "
                           "try fewer things in the comparison")
    out["ai"] = content.strip()
    out["model"] = model
    return out
