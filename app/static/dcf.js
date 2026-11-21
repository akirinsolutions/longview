/* Longview — discounted cash flow math, shared by the Company page and the tests.
   All rates are percentages; the terminal growth rate is fixed at 2.5%. */
(function (root) {
  const TERMINAL_GROWTH = 0.025;

  function valuePerShare(o) {
    const fcf = Number(o.fcf);
    const shares = Number(o.shares);
    const growth = Number(o.growth);
    const discount = Number(o.discount);
    const years = Math.max(1, Math.min(30, Math.round(Number(o.years) || 5)));
    if (!(fcf > 0) || !(shares > 0)) return null;
    if (!Number.isFinite(growth) || !(discount > 2.5)) return null;
    const g = growth / 100, r = discount / 100;
    let pv = 0, flow = fcf;
    for (let y = 1; y <= years; y++) {
      flow *= 1 + g;
      pv += flow / Math.pow(1 + r, y);
    }
    const terminal = flow * (1 + TERMINAL_GROWTH) / (r - TERMINAL_GROWTH);
    pv += terminal / Math.pow(1 + r, years);
    const equity = pv + (Number(o.cash) || 0) - (Number(o.debt) || 0);
    return equity / shares;
  }

  /* The growth that makes valuePerShare equal a target price. One equation,
     one unknown: the discount rate, years, and terminal growth stay fixed.
     Returns {growth, bounded, value} or null. Growth is a percentage. */
  function impliedGrowth(o) {
    const price = Number(o.price);
    if (!(price > 0)) return null;
    const at = (g) => valuePerShare(Object.assign({}, o, { growth: g }));
    const low = at(-99), high = at(500);
    if (low == null || high == null) return null;
    if (price <= low) return { growth: -99, bounded: "low", value: low };
    if (price >= high) return { growth: 500, bounded: "high", value: high };
    let lo = -99, hi = 500;
    for (let i = 0; i < 120; i++) {
      const mid = (lo + hi) / 2;
      if (at(mid) < price) lo = mid;
      else hi = mid;
    }
    const growth = (lo + hi) / 2;
    return { growth, bounded: null, value: at(growth) };
  }

  const api = { TERMINAL_GROWTH, valuePerShare, impliedGrowth };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.DCF = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
