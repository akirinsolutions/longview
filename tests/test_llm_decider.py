"""The LLM decider ("AI runs it"), tested fully offline.

``risk._post_llm`` is monkeypatched in every test — the RAM rule: no
model is ever really called. The two properties under test: the prompt
is built field by field from the no-lookahead context, and a model that
fails or garbles becomes a quiet "no trades" day, never a crashed run.
"""
import json

from app import risk, strategy_lab


def _ctx():
    """A hand-built decision-day context in the exact engine shape."""
    return {
        "date": "2021-03-15",
        "plan": {"symbols": ["A"],
                 "text": "buy A when it dips 10%, check monthly"},
        "portfolio": {
            "cash": 50_000.0, "equity": 100_000.0,
            "positions": [{"symbol": "A", "qty": 500.0,
                           "cost_basis": 100.0, "value": 45_000.0,
                           "pnl_pct": -10.0, "drop_from_cost_pct": 10.0,
                           "drop_from_peak_pct": 12.0, "days_held": 30}],
        },
        "prices": {"A": {"close": 90.0, "1w": 95.0, "1m": 92.0,
                         "3m": 88.0, "1y": 105.0,
                         "52w_high": 110.0, "52w_low": 85.0}},
        "triggered": [{"symbol": "A", "kind": "drop_from_cost",
                       "threshold_pct": 10.0, "drop_pct": 10.0}],
        "research": {"A": "A is a fine company, cheap right now.",
                     "_skips": {"A": "the arXiv lookup failed (timed out)"}},
        "ever_held": True,
    }


# ---------------------------------------------------------------------------
# The prompt: only what the engine put in the context reaches the model
# ---------------------------------------------------------------------------

def test_prompt_states_what_was_known_that_day():
    system, user = strategy_lab.build_decision_prompt(_ctx())
    assert "buy A when it dips 10%" in system      # the strategy, verbatim
    assert "STRICT JSON" in system
    assert "2021-03-15" in user
    assert "$50,000" in user and "$100,000" in user   # cash and equity
    assert "cost $100.00" in user                  # the position
    assert "$90.00" in user                        # today's close
    assert "A is a fine company" in user           # the research
    assert "A is down 10.0% from its cost" in user  # the firing trigger
    assert "skipped" in user                       # the honest research skip


def test_prompt_is_built_field_by_field_not_by_dumping_the_context():
    c = _ctx()
    c["planted_future_data"] = "SECRET-TOKEN-999"
    system, user = strategy_lab.build_decision_prompt(c)
    assert "SECRET-TOKEN-999" not in system + user


def test_prompt_for_an_empty_portfolio_says_so():
    c = _ctx()
    c["portfolio"]["positions"] = []
    c["ever_held"] = False
    c["triggered"] = []
    system, user = strategy_lab.build_decision_prompt(c)
    assert "never held a position" in user
    assert "Drop triggers firing today: none" in user


# ---------------------------------------------------------------------------
# The decider: model JSON -> safe trades; failure -> a quiet no-trade day
# ---------------------------------------------------------------------------

def test_decider_turns_model_json_into_trades(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return (json.dumps({"trades": [{"symbol": "A", "side": "buy",
                                        "weight": 0.5}],
                            "note": "the dip is 10%, the strategy says add"}),
                "fake-model")
    monkeypatch.setattr(risk, "_post_llm", fake)
    decision = strategy_lab.make_llm_decider()(_ctx())
    assert decision["trades"] == [{"symbol": "A", "side": "buy",
                                   "weight": 0.5}]
    assert "dip" in decision["note"]


def test_decider_clamps_and_drops_overreaching_trades(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return (json.dumps({"trades": [
            {"symbol": "A", "side": "buy", "weight": 1.5},  # clamped to 1
            {"symbol": "GHOST", "side": "buy", "weight": 0.3},  # off-universe
            {"symbol": "A", "side": "trade", "weight": 0.2},  # bad side
            {"symbol": "A", "side": "sell"},            # no weight
        ]}), "fake-model")
    monkeypatch.setattr(risk, "_post_llm", fake)
    decision = strategy_lab.make_llm_decider()(_ctx())
    assert decision["trades"] == [{"symbol": "A", "side": "buy",
                                   "weight": 1.0}]


def test_model_outage_is_a_quiet_no_trade(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(risk, "_post_llm", fake)
    decision = strategy_lab.make_llm_decider()(_ctx())
    assert decision["trades"] == []
    assert "unavailable" in decision["note"]
    assert "connection refused" in decision["note"]


def test_unreadable_answer_is_a_quiet_no_trade(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return "```json\n{not valid json\n```", "fake-model"
    monkeypatch.setattr(risk, "_post_llm", fake)
    decision = strategy_lab.make_llm_decider()(_ctx())
    assert decision["trades"] == []
    assert "did not read" in decision["note"]


def _flat_prices(n=30):
    from datetime import date, timedelta
    return {"A": {str(date(2021, 1, 4) + timedelta(days=i)): 100.0
                  for i in range(n)}}


def test_llm_decider_runs_a_full_backtest(monkeypatch):
    bought = {"n": 0}

    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        bought["n"] += 1
        if bought["n"] == 1:
            return (json.dumps({"trades": [{"symbol": "A", "side": "buy",
                                            "weight": 1.0}],
                                "note": "initial deploy"}), "fake-model")
        return (json.dumps({"trades": [], "note": "holding"}), "fake-model")
    monkeypatch.setattr(risk, "_post_llm", fake)

    p = strategy_lab.make_plan(["A"], frequency="month",
                               text="buy everything on day one")
    r = strategy_lab.simulate(p, _flat_prices(), strategy_lab.make_llm_decider())
    assert bought["n"] == r["decisions"] == 2     # day one, then the next month
    assert r["trades"] == 1
    assert r["equity"][0] == 100_000.0            # flat price, zero cost
    assert r["log"][0]["note"] == "initial deploy"


def test_model_outage_never_sinks_the_run(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        raise RuntimeError("the model server is down")
    monkeypatch.setattr(risk, "_post_llm", fake)

    p = strategy_lab.make_plan(["A"], frequency="month")
    r = strategy_lab.simulate(p, _flat_prices(), strategy_lab.make_llm_decider())
    assert r["trades"] == 0
    assert r["equity"] == [100_000.0] * 30
    assert all("unavailable" in e["note"] for e in r["log"])
