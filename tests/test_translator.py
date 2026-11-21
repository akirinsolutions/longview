"""The plain-English reader: every classic pattern, plus graceful failure."""
from app import translator


def test_buy_and_hold_with_symbol():
    s = translator.parse("buy and hold AAPL")
    assert s["ok"] and s["rule"] == "buy_and_hold"
    assert s["symbol"] == "AAPL"
    assert s["confidence"] == "high"


def test_buy_and_hold_default_symbol():
    s = translator.parse("buy and hold")
    assert s["rule"] == "buy_and_hold"
    assert s["symbol"] == "SPY"  # default


def test_buy_the_dip_with_percent():
    s = translator.parse("buy the dip when it drops 12% below its recent high")
    assert s["rule"] == "buy_the_dip"
    assert s["params"]["drop_pct"] == 12
    assert s["symbol"] == "SPY"  # no ticker named -> default


def test_sma_cross_slash_form():
    s = translator.parse("50/200 day moving average crossover on QQQ")
    assert s["rule"] == "sma_cross"
    assert s["params"] == {"fast": 50, "slow": 200}
    assert s["symbol"] == "QQQ"


def test_sma_cross_words_form():
    s = translator.parse("use 20 and 100 day moving averages")
    assert s["rule"] == "sma_cross"
    assert s["params"] == {"fast": 20, "slow": 100}


def test_momentum_with_months():
    s = translator.parse("ride 6 month momentum and sell if it turns negative")
    assert s["rule"] == "momentum"
    assert s["params"]["months"] == 6
    assert s["symbol"] == "SPY"  # 'negative'/'turns' are not tickers


def test_dca_with_amount():
    s = translator.parse("invest $500 every month into SPY")
    assert s["rule"] == "dca"
    assert s["params"]["monthly_amount"] == 500
    assert s["symbol"] == "SPY"


def test_gibberish_falls_back_to_buy_and_hold_low_confidence():
    s = translator.parse("make me rich with quantum vibes")
    assert s["ok"] is False
    assert s["rule"] == "buy_and_hold"
    assert s["confidence"] == "low"


def test_summarize_mentions_symbol_and_rule_idea():
    line = translator.summarize("sma_cross", {"fast": 50, "slow": 200}, "SPY")
    assert "SPY" in line and "50" in line and "200" in line


def test_symbol_hint_used_when_text_names_no_ticker():
    s = translator.parse("buy the dip", "AAPL")
    assert s["symbol"] == "AAPL"
    assert "AAPL" in s["summary"]


def test_named_ticker_beats_symbol_hint():
    s = translator.parse("buy the dip in TSLA", "SPY")
    assert s["symbol"] == "TSLA"
    assert "TSLA" in s["summary"]


def test_translate_passes_hint_to_summary(monkeypatch):
    monkeypatch.setattr(translator, "_llm_spec", lambda *a: None)
    s = translator.translate("buy and hold", "MSFT")
    assert s["symbol"] == "MSFT"
    assert "MSFT" in s["summary"]


# The user's actual report: a long, colloquial strategy that starts with
# "buy and hold". The reader must not let the English word "but" become a
# ticker, and it must admit it can only test the buy-and-hold part.
_DIP_REPORT = (
    "buy and hold, but if there is a dip of over 20%, sell everything, "
    "and reinvest when it there is a dip of 50% compared to the original "
    "20% dip price. this should beat buy and hold because you have more "
    "stocks when you reinvest everything in the dip"
)


def test_english_words_are_not_tickers():
    s = translator.parse(_DIP_REPORT)
    assert s["symbol"] == "SPY"  # no ticker in the words -> default
    assert "BUT" not in s["summary"].upper()


def test_english_words_are_not_tickers_with_hint():
    s = translator.parse(_DIP_REPORT, "QQQ")
    assert s["symbol"] == "QQQ"
    assert s["summary"] == "Buy QQQ and never sell."


def test_dip_flavoured_buy_and_hold_gets_honest_note():
    s = translator.parse(_DIP_REPORT, "QQQ")
    assert s["rule"] == "buy_and_hold"
    assert s.get("note")
    assert "five rules" in s["note"]
    assert s["confidence"] == "medium"


def test_plain_buy_and_hold_gets_no_note():
    s = translator.parse("buy and hold AAPL")
    assert s.get("note") is None
    assert s["confidence"] == "high"


def test_note_applies_on_the_llm_path_too(monkeypatch):
    # Run the real LLM path: a fake HTTP response whose JSON spec the
    # validator accepts. The dip words must still earn the honest note.
    import httpx

    monkeypatch.setenv("PROOF_LLM_KEY", "test-key")

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                '{"rule": "buy_and_hold", "params": {}, "symbol": "SPY"}')}}]}

    monkeypatch.setattr(httpx, "post",
                        lambda *a, **kw: FakeResp())
    s = translator.translate(_DIP_REPORT, "SPY")
    assert s["source"] == "llm"
    assert s["symbol"] == "SPY"
    assert s.get("note")
    assert s["confidence"] == "medium"
