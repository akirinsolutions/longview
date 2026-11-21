"""The chat bubble can open a Smart Money page or a backtest.

These are deterministic routes, so they work even when the language model
is unavailable, and they must not fire on ordinary questions.
"""
from app.main import _action_answer, _plan_action


def test_smart_money_phrases():
    for q in ("who holds Apple?", "which funds own Nvidia",
              "do the funds hold Tesla", "check Apple in smart money",
              "is Microsoft held by the funds"):
        a = _plan_action(q)
        assert a and a["type"] == "smart_money", q
        assert a["query"]


def test_smart_money_trims_leading_articles():
    a = _plan_action("who owns the Coca-Cola Company?")
    assert a == {"type": "smart_money", "query": "Coca-Cola Company"}


def test_backtest_phrase_keeps_strategy_symbol_and_years():
    a = _plan_action("backtest buy the dip on AAPL for 10 years")
    assert a == {
        "type": "backtest", "text": "buy the dip",
        "symbol": "AAPL", "years": 10,
    }


def test_backtest_defaults():
    a = _plan_action("backtest buy and hold")
    assert a["symbol"] == "SPY"
    assert a["years"] == 10
    assert a["text"] == "buy and hold"


def test_backtest_reads_symbol_after_with():
    a = _plan_action("backtest AAPL with buy and hold")
    assert a["text"] == "buy and hold"
    assert a["symbol"] == "AAPL"


def test_how_would_have_done_is_a_backtest():
    a = _plan_action("how would buy the dip have done?")
    assert a["type"] == "backtest"
    assert a["text"] == "buy the dip"


def test_risk_fill_phrases():
    for q in ("do risk", "run the risk fill", "fill risk",
              "auto-fill the risk", "autofill the risk",
              "can you do the risk for me"):
        a = _plan_action(q)
        assert a == {"type": "risk_fill"}, q


def test_risk_word_alone_does_not_fire():
    for q in ("risky", "what is the risk", "what is the risk page?",
              "explain risk", "is this holding risky?"):
        assert _plan_action(q) is None, q


def test_risk_fill_answer_is_plain():
    ans = _action_answer({"type": "risk_fill"})
    assert "Risk" in ans and "Not advice" in ans


def test_ordinary_questions_do_not_fire_actions():
    for q in ("What is my biggest holding?",
              "How would you value Apple?",
              "What does Apple do?",
              "Which currency is most of my cost in?"):
        assert _plan_action(q) is None, q


def test_action_answers_are_plain():
    smart = _action_answer({"type": "smart_money", "query": "Apple"})
    assert "Smart Money" in smart and "Not advice" in smart
    bt = _action_answer({"type": "backtest", "text": "buy the dip",
                         "symbol": "AAPL", "years": 10})
    assert "backtest" in bt and "AAPL" in bt and "10 years" in bt


# ---------------------------------------------------------------------------
# The bubble can see the current page and the saved notebook
# ---------------------------------------------------------------------------

def test_page_context_company():
    from app.main import _page_context
    line = _page_context({
        "kind": "company", "symbol": "AAPL", "name": "Apple",
        "price": 342.37, "currency": "USD", "change_pct": 1.2,
        "market_cap": 4.4e12, "pe": 35.2,
        "about": "Apple designs and sells the iPhone and the Mac.",
        "dcf": "Value per share $198.02",
    })
    assert "Apple" in line and "342.37" in line
    assert "iPhone" in line and "198.02" in line


def test_page_context_lab():
    from app.main import _page_context
    line = _page_context({
        "kind": "lab", "text": "buy the dip", "symbol": "AAPL",
        "years": 5, "verdict": "The strategy lost to buy and hold.",
    })
    assert "buy the dip" in line and "AAPL" in line and "5" in line
    assert "lost to buy and hold" in line


def test_page_context_simple_pages():
    from app.main import _page_context
    assert "Smart Money" in _page_context({"kind": "money", "sub": "holdings"})
    assert "Notebook" in _page_context({"kind": "notes"}) or "Notes" in _page_context({"kind": "notes"})
    assert "Home" in _page_context({"kind": "home"})


def test_page_context_risk_and_economy():
    from app.main import _page_context
    line = _page_context({"kind": "risk", "n": 5, "n_live": 4,
                          "value": 10000, "scenario": 9800,
                          "currency": "USD"})
    assert "Risk" in line and "9800" in line and "USD" in line
    eco = _page_context({"kind": "economy", "sub": "stocks"})
    assert "Economy" in eco and "stocks" in eco
    eco_top = _page_context({"kind": "economy"})
    assert "Economy" in eco_top and "slice" not in eco_top


def test_page_context_ignores_garbage():
    from app.main import _page_context
    assert _page_context({}) == ""
    assert _page_context({"kind": "zzz"}) == ""
    assert _page_context(None) == ""


def test_notes_context_trims_and_orders(monkeypatch):
    from app import notes as notes_mod
    from app.main import _notes_context
    monkeypatch.setattr(notes_mod, "load_pages", lambda: [
        {"id": "n1", "title": "Old page", "body": "old thoughts",
         "updated": 1, "snippets": []},
        {"id": "n2", "title": "Recent page", "body": "new " * 500,
         "updated": 9, "snippets": [
             {"title": "A saved backtest", "lines": ["line one", "line two"]}]},
    ])
    pages = _notes_context(max_pages=10, max_chars=5000)
    assert pages[0]["title"] == "Recent page"  # most recent first
    assert "line one" in pages[0]["text"]
    assert len(pages[0]["text"]) <= 1200 + 120  # body + snippet, capped


def test_chat_prompt_carries_page_and_notes(monkeypatch):
    import app.main as m
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PROOF_LLM_KEY", "local")
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, **kw):
        captured.update(kw)
        return FakeResp()

    monkeypatch.setattr(m.httpx, "post", fake_post)
    monkeypatch.setattr(m.portfolio, "load_portfolio", lambda: [])
    monkeypatch.setattr(
        m.notes, "load_pages",
        lambda: [{"id": "n1", "title": "Dip ideas",
                  "body": "Buy back when it is 50% off.", "updated": 5,
                  "snippets": []}])

    with TestClient(m.app) as client:
        r = client.post("/api/chat", json={
            "q": "What did I write about dips?",
            "history": [], "currency": "",
            "page": {"kind": "company", "symbol": "AAPL", "name": "Apple"},
        })
    assert r.status_code == 200
    user_msg = captured["json"]["messages"][-1]["content"]
    assert "Apple" in user_msg                       # the current page
    assert "Dip ideas" in user_msg                   # the notebook
    assert "50% off" in user_msg
