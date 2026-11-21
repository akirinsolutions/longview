"""Plain-English in, working strategy out.

Two paths, same output:

1. If a language model is configured (the ``llm`` seam: the request's
   own key if the browser sent one, else the LONGVIEW_LLM_* /
   PROOF_LLM_* environment for any OpenAI-compatible server),
   the model writes the strategy as a small JSON spec. This handles
   basically anything you can describe.
2. Without a key, a built-in rule reader recognizes the classic patterns
   (buy-and-hold, buy-the-dip, moving-average cross, momentum, monthly DCA)
   so the app works fully offline.

Either way the result is a tiny, human-readable spec that the UI shows you
before anything runs — you always see exactly what will be tested.
"""
from __future__ import annotations

import json
import re

import httpx

KNOWN_RULES = {
    "buy_and_hold": "Buy and hold",
    "sma_cross": "Moving-average cross",
    "buy_the_dip": "Buy the dip",
    "momentum": "Momentum",
    "dca": "Monthly dollar-cost averaging",
}

DEFAULT_SYMBOL = "SPY"

_STOPWORDS = {
    "A", "AN", "AND", "OR", "THE", "OF", "TO", "IN", "ON", "FOR", "FROM",
    "WHEN", "WHILE", "IF", "THEN", "BUY", "HOLD", "HOLDS", "BUYING", "BUYER",
    "SELL", "SELLS", "SOLD", "HOLDING", "PRICE", "PRICES", "STOCK", "STOCKS",
    "FUND", "FUNDS", "ETF", "INDEX", "MARKET", "DAILY", "WEEKLY", "MONTHLY",
    "EVERY", "EACH", "ALL", "ANY", "MY", "YOUR", "MYSELF", "IT", "THIS",
    "THAT", "WITH", "AT", "BY", "UP", "DOWN", "DROP", "DROPS", "FALL",
    "FALLS", "RISE", "RISES", "GROW", "GET", "GOT", "SMA", "MA", "AVG",
    "AVERAGE", "MOVING", "CROSS", "CROSSES", "CROSSOVER", "CROSSING",
    "ABOVE", "BELOW", "DIP", "DIPS", "PULLBACK", "PULLBACKS", "HIGH",
    "HIGHS", "LOW", "LOSES", "WIN", "WINS", "MOMENTUM", "RECOVER",
    "RECOVERY", "RECOVERS", "BACK", "AGAIN", "CASH", "INVESTED",
    "INVEST", "INVESTING", "TRADING", "TRADE", "STRATEGY", "RULE",
    "COST", "AVG", "US", "USD",
    # words that could otherwise masquerade as tickers in free text
    "ITS", "ITSELF", "RECENT", "NEGATIVE", "POSITIVE", "TURNS", "TURN",
    "ENTRY", "EXIT", "ENTER", "ENTERS", "CLOSE", "CLOSES", "OPENS",
    "OPEN", "OVER", "UNDER", "AFTER", "BEFORE", "DURING", "FIRST",
    "LAST", "NEXT", "YEAR", "YEARS", "MONTH", "MONTHS", "DAY", "DAYS",
    "WEEK", "WEEKS", "PERCENT", "POINT", "POINTS", "GAIN", "GAINS",
    "LOSS", "LOSSES", "ALREADY", "ONLY", "MORE", "MOST", "MUCH", "VERY",
    "TOO", "JUST", "REALLY", "WANT", "WANTS", "NEED", "NEEDS", "LIKE",
    "LIKES", "TRY", "TRIES", "TEST", "RUN", "SOME", "SUCH", "THEN",
    "HERE", "THERE", "WHICH", "WHO", "WHAT", "WHERE", "WHY", "HOW",
    "VERY", "OWN", "SAME", "ANYMORE", "TOGETHER", "INTO", "AVERAGES",
    "RIDE", "RIDES", "RIDING", "MAKE", "ME", "MY", "WE", "YOU", "YOUR",
    "US", "HE", "SHE", "IT", "SO", "NO", "NOT", "YES", "STILL", "KEEP",
    "KEEPING", "WATCH", "WATCHING", "FOLLOW", "FOLLOWING", "SOMEONE",
    "ANYONE", "EVERYONE", "PEOPLE",
    # function words and strategy verbs that read like tickers in free text
    # ("buy and hold, BUT if..." must never yield the symbol BUT)
    "BUT", "IS", "ARE", "WAS", "WERE", "BE", "BEEN", "HAS", "HAVE",
    "HAD", "DOES", "DID", "NEVER", "ALWAYS", "BECAUSE", "SINCE",
    "UNLESS", "UNTIL", "EVERYTHING", "SOMETHING", "NOTHING", "REINVEST",
    "REINVESTS", "REINVESTED", "COMPARED", "COMPARE", "BEAT", "BEATS",
    "SHOULD", "WOULD", "COULD", "MIGHT", "MUST", "SHORT", "SHORTS",
    "SELLING", "SELLER", "ORIGINAL", "GONE", "GOES", "GOING",
}


def _extract_symbol(text: str) -> str | None:
    """Find something that looks like a ticker; None if nothing plausible."""
    # Explicit "in SPY" / "on AAPL" wins.
    m = re.search(r"\b(?:in|on|of)\s+([A-Za-z]{1,5})\b", text)
    if m and m.group(1).upper() not in _STOPWORDS:
        return m.group(1).upper()
    for tok in re.findall(r"\b[A-Za-z]{1,5}\b", text.upper()):
        if tok not in _STOPWORDS:
            return tok
    return None


def _first_percent(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    return float(m.group(1)) if m else None


def _two_numbers(text: str) -> tuple[int, int] | None:
    """First two plausible window sizes, e.g. '50/200' or '20 and 100'."""
    m = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
    else:
        nums = [int(n) for n in re.findall(r"\b(\d{1,4})\b", text)
                if 1 <= int(n) <= 500]
        if len(nums) < 2:
            return None
        a, b = nums[0], nums[1]
    if a > b:
        a, b = b, a
    if a < 1 or b < a:
        return None
    return a, b


def summarize(rule: str, params: dict, symbol: str) -> str:
    """The human-readable 'here's what I understood you to say' line."""
    p = params or {}
    if rule == "buy_and_hold":
        return f"Buy {symbol} and never sell."
    if rule == "sma_cross":
        return (f"Invest in {symbol} when its {int(_g(p, 'fast', 50))}-day average is "
                f"above its {int(_g(p, 'slow', 200))}-day average; hold cash otherwise.")
    if rule == "buy_the_dip":
        return (f"Buy {symbol} when it falls {p.get('drop_pct', 8)}% below its "
                f"{p.get('lookback_days', 90)}-day high; sell once it gets back to that high.")
    if rule == "momentum":
        return (f"Invest in {symbol} while it's above where it was "
                f"{p.get('months', 12)} months ago; hold cash otherwise.")
    if rule == "dca":
        return (f"Invest ${p.get('monthly_amount', 1000):,.0f} in {symbol} at the start "
                f"of every month, and never sell.")
    return f"Test the '{rule}' strategy on {symbol}."


def _g(p: dict, key: str, default):
    try:
        return p[key]
    except (KeyError, TypeError):
        return default


# Signals that the words describe a dip strategy (sell into drops, buy
# back, short ...) that no single one of the five rules can express.
_DIP_SIGNALS = (
    r"\bsell\b|\bsells\b|\bsold\b",
    r"reinvest",
    r"\bshort\b",
    r"\bdip\b|\bpullback\b|\bcrash\b",
)


def _mismatch_note(text: str, spec: dict) -> str | None:
    """A plain-English warning for when the matched rule is only part of
    what the person described. 'Buy and hold, but sell everything in a
    dip' is really a dip strategy; testing the buy-and-hold part is fine,
    but the card must say that is all we tested."""
    if spec.get("rule") != "buy_and_hold":
        return None
    t = (text or "").lower()
    hits = sum(bool(re.search(p, t)) for p in _DIP_SIGNALS)
    if hits >= 2:
        return ("You also described selling into dips and buying back — "
                "that isn't one of my five rules, so I only tested the "
                "plain buy-and-hold part of your idea.")
    return None


def _annotate(spec: dict, text: str) -> dict:
    note = _mismatch_note(text, spec)
    if note:
        spec["note"] = note
        if spec.get("confidence") == "high":
            spec["confidence"] = "medium"
    return spec


def parse(text: str, symbol: str | None = None) -> dict:
    """Rule-based reader: no key, no network, fully predictable."""
    t = (text or "").lower()
    symbol = _extract_symbol(text) or symbol or DEFAULT_SYMBOL
    pct = _first_percent(t)

    rule: str | None = None
    params: dict = {}

    if re.search(r"buy[\s-]*and[\s-]*hold|just (buy|hold)|do nothing|leave it", t):
        rule = "buy_and_hold"
    elif re.search(r"moving average|moving-average|\bsma\b|\bma\b|crossover|cross (above|below)", t):
        wins = _two_numbers(t)
        if wins:
            rule = "sma_cross"
            params = {"fast": wins[0], "slow": wins[1]}
        elif "50" in t and "200" in t:
            rule = "sma_cross"
            params = {"fast": 50, "slow": 200}
    elif re.search(r"\bdip\b|pullback|drop|decline|crash|selloff|sell-off", t):
        rule = "buy_the_dip"
        params = {
            "drop_pct": pct if pct and 1 <= pct <= 90 else 8,
            "lookback_days": 90,
            "max_hold_days": 252,
        }
    elif "momentum" in t:
        rule = "momentum"
        nums = re.findall(r"\b(\d{1,3})\s*(?:-| )?month", t)
        params = {"months": int(nums[0]) if nums else 12}
    elif re.search(r"dollar.cost|each month|every month|monthly|\bregularly\b|\bsteady\b", t):
        rule = "dca"
        m = re.search(r"\$\s?([\d,]+)", t)
        amount = float(m.group(1).replace(",", "")) if m else 1000.0
        params = {"monthly_amount": amount if 10 <= amount <= 1_000_000 else 1000.0}

    if rule is None:
        return {
            "ok": False,
            "rule": "buy_and_hold",
            "symbol": symbol,
            "params": {},
            "summary": ("I couldn't pin down the exact rule, so I'll test a plain "
                        "buy-and-hold instead — or pick one of the examples."),
            "confidence": "low",
            "source": "rules",
        }

    confidence = "high" if rule in ("buy_and_hold", "dca") else "medium"
    return _annotate({
        "ok": True,
        "rule": rule,
        "symbol": symbol,
        "params": params,
        "summary": summarize(rule, params, symbol),
        "confidence": confidence,
        "source": "rules",
    }, text)


# ---------------------------------------------------------------------------
# Optional LLM path
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You convert a person's description of an investment strategy into a "
    "backtest spec. Reply with ONLY a JSON object, no other text: "
    '{"rule": <one of "buy_and_hold", "sma_cross", "buy_the_dip", "momentum", '
    '"dca">, "params": {...}, "symbol": <ticker or null>}. '
    "Param shapes: sma_cross {\"fast\": number, \"slow\": number}; "
    "buy_the_dip {\"drop_pct\": number 1-90, \"lookback_days\": number, "
    "\"max_hold_days\": number}; momentum {\"months\": number}; "
    "dca {\"monthly_amount\": number}; buy_and_hold {}. "
    "Use the ticker the person named if any, else null. "
    "If the description fits no rule, use the closest one and keep params minimal."
)


def _llm_spec(text: str, symbol: str | None = None) -> dict | None:
    from . import llm  # one seam: request override > environment

    cfg = llm.resolve()
    key = cfg["key"]
    if not key:
        return None
    base, model = cfg["base"], cfg["model"]
    try:
        r = httpx.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": 800,  # thinking models spend the budget on
                                    # reasoning first; 300 left the JSON empty
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            },
            timeout=30,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        spec = json.loads(m.group(0))
        return _validate_llm(spec, text, symbol)
    except Exception:
        return None  # any failure falls back to the rule reader


def _validate_llm(spec: dict, text: str, symbol: str | None = None) -> dict | None:
    rule = spec.get("rule")
    if rule not in KNOWN_RULES:
        return None
    params = spec.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    # Coerce to the same param shapes the engine expects.
    out: dict = {}
    for k, default in (("fast", 50), ("slow", 200), ("drop_pct", 8),
                       ("lookback_days", 90), ("max_hold_days", 252),
                       ("months", 12), ("monthly_amount", 1000)):
        if k in params:
            try:
                out[k] = float(params[k])
            except (TypeError, ValueError):
                out[k] = float(default)
    symbol = (spec.get("symbol") or _extract_symbol(text) or symbol or DEFAULT_SYMBOL).upper()
    return _annotate({
        "ok": True,
        "rule": rule,
        "symbol": symbol,
        "params": out,
        "summary": summarize(rule, out, symbol),
        "confidence": "high",
        "source": "llm",
    }, text)


def translate(text: str, symbol: str | None = None) -> dict:
    """Best available: LLM if configured and it produced a valid spec,
    otherwise the deterministic rule reader.

    ``symbol`` is the instrument the form is pointing at: it's used when the
    words themselves don't name a ticker, so the summary reads about the same
    thing the backtest will actually run on."""
    spec = _llm_spec(text, symbol)
    if spec is not None:
        return spec
    return parse(text, symbol)
