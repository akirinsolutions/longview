"""The decade behind the economy picture: 2015 to 2024, USD billions.

The tree is a single end-2024 picture; the charts want a second
dimension, so every node gets a ten-year history. In order of how
measured each part is:

* **The world** — the UBS Global Wealth Report's own record. 2023 and
  2024 are the exact totals the editions state (449,965 / 470,508 bn);
  the earlier points come from the report's chart of global wealth, so a
  few carry ±0.1-0.5k bn of digitisation error, and 2022 rests on a
  different source than the rest, per the report's own footnote.
* **The four regions** — anchored on the report's 2023 and 2024
  sub-regional tables, then walked back to 2015 at the since-2008
  growth the reports state for each region (Americas +146%, EMEA +44%,
  APAC +177%). "Asia-Pacific & rest" is the implied residual — the
  world minus the other three, every year — which keeps the four
  regions summing to the world exactly.
* **Everything deeper** — asset classes and their branches have no
  published by-year record: the seven top slices inherit the world's
  shape with flat shares, and the rest walk back at the node's own
  growth rate. Both are assumptions, and the page labels them as such.

The page recomputes each node's series locally from the shapes here, so
tuning a rate or letting the AI rewrite a level re-shapes every history
chart without a round trip.
"""
from __future__ import annotations

from .economy_tree import REGION_NAMES

YEARS = tuple(range(2015, 2025))
N = len(YEARS)
LAST_YEAR = YEARS[-1]  # 2024: the year the tree is built from

#: Global household wealth, USD bn, end of year, 2015 to 2024.
WORLD_BN = (
    285200.0, 299100.0, 342100.0, 344300.0, 371000.0,
    403900.0, 443800.0, 431000.0, 449965.0, 470508.0,
)

# (name, 2023 bn, 2024 bn, total wealth growth since 2008 per the
# reports, or None for the residual region — the world minus the other
# three, so the four always add up to the world in every year).
_REGIONS = (
    ("United States & Canada", 156999.0, 174667.0, 1.46),
    ("Europe", 109583.0, 110015.0, 0.44),
    ("China", 97774.0, 100984.0, 1.77),
    ("Asia-Pacific & rest", None, None, None),
)

_RESIDUAL = "Asia-Pacific & rest"
_BASE_YEAR = 2008  # the year the reports measure growth from


def _cagr(total_growth: float, span: int) -> float:
    """A stated total growth (+146% over 15 years) as a per-year rate."""
    return (1.0 + total_growth) ** (1.0 / span) - 1.0


def region_values(name: str) -> tuple[float, ...]:
    """One region's ten points, USD bn, oldest first.

    The named regions take the report's 2023 and 2024 anchors and walk
    back at the stated since-2008 rate; the residual is the difference,
    which keeps the four regions summing to the world in every year.
    """
    if name == _RESIDUAL:
        others = [region_values(n) for n in REGION_NAMES if n != _RESIDUAL]
        return tuple(round(WORLD_BN[i] - sum(o[i] for o in others), 1)
                     for i in range(N))
    _, a23, a24, growth = next(r for r in _REGIONS if r[0] == name)
    rate = _cagr(growth, 2023 - _BASE_YEAR)
    out = []
    for y in YEARS:
        if y == 2023:
            out.append(a23)
        elif y == LAST_YEAR:
            out.append(a24)
        else:
            out.append(round(a23 / (1.0 + rate) ** (2023 - y), 1))
    return tuple(out)


def world_shape() -> tuple[float, ...]:
    """The world series as a fraction of its 2024 value (1.0 in 2024)."""
    last = WORLD_BN[-1]
    return tuple(v / last for v in WORLD_BN)


def region_shape(name: str) -> tuple[float, ...]:
    """A region's ten points as a fraction of its own 2024 value."""
    vals = region_values(name)
    last = vals[-1]
    return tuple(v / last for v in vals)


def node_values(node_name: str, level: int, value_2024_bn: float,
                g: float) -> tuple[float, ...]:
    """One node's ten points, USD bn, anchored on its own 2024 value.

    The world and the seven top slices inherit the world's shape; a
    geography leaf inherits its region's shape; everything in between
    walks back at the node's own growth rate. The series always ends on
    the node's displayed value, whatever the tree's edits have done.
    """
    if level <= 1:
        shape = world_shape()
    elif level >= 7 and node_name in REGION_NAMES:
        shape = region_shape(node_name)
    else:
        rate = float(g or 0.0) / 100.0
        shape = tuple(1.0 / (1.0 + rate) ** (LAST_YEAR - y) for y in YEARS)
    last = shape[-1]
    return tuple(round(value_2024_bn * v / last, 1) for v in shape)


def series_payload() -> dict:
    """The shapes the page needs: the years, the world, and each region."""
    return {
        "years": list(YEARS),
        "last_year": LAST_YEAR,
        "world": [round(v, 1) for v in WORLD_BN],
        "regions": {name: [round(v, 1) for v in region_values(name)]
                    for name in REGION_NAMES},
    }
