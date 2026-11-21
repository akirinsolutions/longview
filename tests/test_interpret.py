"""The interpreter: the user's words -> a validated plan.

The deterministic reader (``draft_from_text``) is tested directly. The
LLM leg is tested with ``app.risk._post_llm`` monkeypatched — the RAM
rule: no model is ever really called from a test, and an unconfigured
environment must result in zero model calls.
"""
import json

import pytest

from app import risk, strategy_lab


# ---------------------------------------------------------------------------
# The deterministic reader
# ---------------------------------------------------------------------------

def test_draft_reads_a_dip_buyer():
    d = strategy_lab.draft_from_text(
        "I want to own TSLA and NVDA. I check every month, and when one "
        "drops 15% I add 10% more, then sell all once it has risen 30%.")
    assert d["symbols"] == ["TSLA", "NVDA"]
    assert d["frequency"] == "month"
    trig = d["triggers"][0]
    assert trig["kind"] == "drop_from_peak"
    assert trig["pct"] == 15
    assert d["on_drop"] == "add"
    assert d["add_weight"] == pytest.approx(0.10)
    assert d["exit_pct"] == 30
    assert d["research"] is False


def test_draft_reads_a_cost_stop():
    d = strategy_lab.draft_from_text(
        "I hold AAPL. If it is 25% below my cost, sell everything.")
    assert d["symbols"] == ["AAPL"]
    trig = d["triggers"][0]
    assert trig["kind"] == "drop_from_cost"
    assert trig["pct"] == 25
    assert d["on_drop"] == "sell_all"
    assert d["exit_pct"] is None       # the 25% is the drop, not a gain


def test_draft_reads_research_and_take_profit():
    d = strategy_lab.draft_from_text(
        "Quarterly, I research the web for TSM and take profits at 30%.")
    assert d["symbols"] == ["TSM"]
    assert d["frequency"] == "quarter"
    assert d["triggers"] == []
    assert d["exit_pct"] == 30
    assert d["research"] is True


def test_draft_uses_form_symbols_when_the_text_names_none():
    d = strategy_lab.draft_from_text("I average down on the dips",
                                     symbols=["AAPL"])
    assert d["symbols"] == ["AAPL"]


def test_draft_reads_start_cash():
    assert strategy_lab.draft_from_text(
        "I start with $50k and check weekly.")["start_cash"] == 50_000.0
    assert strategy_lab.draft_from_text(
        "I have $100,000 to put in.")["start_cash"] == 100_000.0


@pytest.mark.parametrize("phrase, want", [
    ("I check twice a month", "two_weeks"),
    ("I review four times a month", "week"),
    ("I rebalance monthly", "month"),
    ("I look at it every quarter", "quarter"),
    ("I check every two weeks", "two_weeks"),
    ("I look at it weekly", "week"),
    ("I rebalance biweekly", "two_weeks"),
])
def test_draft_reads_cadence_phrases(phrase, want):
    assert strategy_lab.draft_from_text(phrase)["frequency"] == want


def test_interpret_empty_text_raises():
    with pytest.raises(ValueError):
        strategy_lab.interpret_strategy("")


def test_interpret_returns_a_validated_plan_with_the_words_kept():
    text = ("I want to own TSLA and NVDA. I check every month, and when "
            "one drops 15% I add 10% more.")
    plan, source = strategy_lab.interpret_strategy(text, use_llm=False)
    assert source == "words"
    assert plan["symbols"] == ["TSLA", "NVDA"]
    assert plan["targets"] == {"TSLA": 0.5, "NVDA": 0.5}   # equal split
    assert plan["text"] == text
    assert plan["names"] == {}


# ---------------------------------------------------------------------------
# The LLM leg — risk._post_llm is monkeypatched; no real model, ever
# ---------------------------------------------------------------------------

def _fake_plan_json():
    return json.dumps({
        "symbols": ["SPY", "QQQ"],
        "frequency": "week",
        "triggers": [{"kind": "drop_from_peak", "pct": 20,
                      "lookback_days": 252, "rearm": "recover"}],
        "targets": {"SPY": 0.5, "QQQ": 0.5},
        "on_drop": "add", "add_weight": 0.1, "exit_pct": None,
        "research": False, "names": {},
    })


def test_interpret_uses_the_model_when_forced(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return "```json\n" + _fake_plan_json() + "\n```", "fake-model"
    monkeypatch.setattr(risk, "_post_llm", fake)
    plan, source = strategy_lab.interpret_strategy(
        "buy SPY and QQQ, check weekly, add on 20% drops", use_llm=True)
    assert source == "model"
    assert plan["symbols"] == ["SPY", "QQQ"]
    assert plan["frequency"] == "week"
    assert plan["triggers"][0]["pct"] == 20
    assert plan["targets"] == {"SPY": 0.5, "QQQ": 0.5}
    assert plan["text"]  # the user's words are kept for the decider


def test_form_tickers_fix_the_universe(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return _fake_plan_json(), "fake-model"     # no fence this time
    monkeypatch.setattr(risk, "_post_llm", fake)
    plan, source = strategy_lab.interpret_strategy(
        "I trade AAPL and MSFT", symbols=["AAPL", "MSFT"], use_llm=True)
    assert source == "model"
    assert plan["symbols"] == ["AAPL", "MSFT"]    # the model's tickers dropped
    assert plan["targets"] == {"AAPL": 0.5, "MSFT": 0.5}
    assert plan["triggers"][0]["pct"] == 20      # but its rules survive


def test_model_failure_falls_back_to_words(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        raise RuntimeError("the model server is down")
    monkeypatch.setattr(risk, "_post_llm", fake)
    plan, source = strategy_lab.interpret_strategy(
        "own TSLA, add on 10% dips, check monthly", use_llm=True)
    assert source == "words"
    assert plan["symbols"] == ["TSLA"]
    assert plan["triggers"][0]["pct"] == 10
    assert plan["on_drop"] == "add"


def test_garbage_model_output_falls_back_to_words(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return "I'm sorry, I can't turn that into JSON.", "fake-model"
    monkeypatch.setattr(risk, "_post_llm", fake)
    plan, source = strategy_lab.interpret_strategy("own TSLA", use_llm=True)
    assert source == "words"
    assert plan["symbols"] == ["TSLA"]


def test_unconfigured_model_is_never_called(monkeypatch):
    monkeypatch.delenv("PROOF_LLM_KEY", raising=False)
    calls = []

    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        calls.append(user)
        raise AssertionError("the model must not be called when unconfigured")
    monkeypatch.setattr(risk, "_post_llm", fake)
    plan, source = strategy_lab.interpret_strategy("own TSLA, check monthly")
    assert source == "words"
    assert calls == []


def test_model_output_is_clamped(monkeypatch):
    raw = {
        "symbols": ["SPY"], "frequency": "daily",
        "triggers": [{"kind": "drop_from_peak", "pct": 150,
                      "lookback_days": 9999, "rearm": "chaos"},
                     "not a dict"],
        "targets": {"SPY": 2.5, "ZZZZ": 1.0},
        "on_drop": "nuke", "add_weight": 7, "exit_pct": 999,
        "research": "yes", "names": {"SPY": "x" * 200},
    }

    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return json.dumps(raw), "fake-model"
    monkeypatch.setattr(risk, "_post_llm", fake)
    plan, source = strategy_lab.interpret_strategy("own SPY", use_llm=True)
    assert source == "model"
    assert plan["frequency"] == "month"       # "daily" is not a cadence
    t = plan["triggers"][0]
    assert t["pct"] == 90
    assert t["lookback_days"] == 504
    assert t["rearm"] == "recover"
    assert plan["targets"] == {"SPY": 1.0}    # 2.5 clamped; ZZZZ dropped
    assert plan["on_drop"] == "hold"
    assert plan["add_weight"] == 0.5
    assert plan["exit_pct"] == 500
    assert plan["research"] is True
    assert plan["names"] == {}                # 200 chars is too long


def test_false_exit_reads_as_no_exit(monkeypatch):
    def fake(system, user, max_tokens=4000, timeout=60.0, config=None):
        return json.dumps({"symbols": ["SPY"], "exit_pct": False}), "fake-model"
    monkeypatch.setattr(risk, "_post_llm", fake)
    plan, source = strategy_lab.interpret_strategy("own SPY", use_llm=True)
    assert source == "model"
    assert plan["exit_pct"] is None
