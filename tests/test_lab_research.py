"""The date-gated research layer, tested fully offline.

The RAM rule applies: no model, no network. A fake ``http_get`` plays
the web — Wikipedia's revisions API and the arXiv Atom feed — and the
tests check the one property that matters: on a simulated date D the
researcher can only read what existed on or before D.
"""
from datetime import date, timedelta

from app import lab_research


class FakeResp:
    def __init__(self, json_data=None, text=""):
        self._j = json_data
        self.text = text

    def json(self):
        return self._j


#: title -> [(revid, timestamp, lead wikitext)], newest last
WIKI_PAGES = {
    "Apple Inc.": [
        ("1000", "2015-03-10T12:00:00Z",
         "== History ==\nApple is a company that made the iPhone by 2015."),
        ("1001", "2016-05-01T09:00:00Z",
         "Apple announced the Vision Pro in 2016."),
    ],
    "BRK": [
        ("2000", "2017-01-01T00:00:00Z",
         "Berkshire exists in this universe from 2017 onward."),
    ],
}


def atom(entries) -> str:
    body = "".join(
        f"<entry><title>{t}</title><id>http://arxiv.org/abs/x{i}</id>"
        f"<summary>{s}</summary><published>{p}T10:00:00Z</published></entry>"
        for i, (t, s, p) in enumerate(entries))
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'


class FakeHttp:
    """Plays the web. ``ranged_atom`` answers the submittedDate range
    query, ``plain_atom`` the undated one; ``raise_on`` (a substring of
    any param value) makes the call blow up like a real one can."""

    def __init__(self, wiki=WIKI_PAGES, ranged_atom="", plain_atom="",
                 raise_on=None):
        self.wiki = wiki
        self.ranged_atom = ranged_atom
        self.plain_atom = plain_atom
        self.raise_on = raise_on
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, params: dict, timeout: float = 30.0) -> FakeResp:
        params = dict(params)
        self.calls.append((url, params))
        if self.raise_on and any(self.raise_on in str(v) for v in params.values()):
            raise RuntimeError("the web is on fire")
        if url.endswith("/w/api.php"):
            return self._wiki(url, params)
        if url.startswith(lab_research.ARXIV_URL):
            text = self.ranged_atom if "submittedDate" in params.get("search_query", "") \
                else self.plain_atom
            return FakeResp(text=text)
        return FakeResp({"ok": False})

    def _wiki(self, url, params):
        title = params.get("titles", "")
        if "revids" in params:
            rev = next((r for r in self.wiki.get(title, [])
                        if r[0] == params["revids"]), None)
            if rev is None:
                return FakeResp({"query": {"pages": {}}})
            return FakeResp({"query": {"pages": {"1": {"id": 1, "revisions": [
                {"revid": rev[0], "timestamp": rev[1], "*": rev[2]}]}}}})
        start = (params.get("rvstarttimestamp") or "")[:10]
        page = self.wiki.get(title)
        if not page:
            return FakeResp({"query": {"pages": {"-1": {
                "id": -1, "title": title, "missing": ""}}}})
        eligible = [r for r in page if r[1][:10] <= start]
        chosen = max(eligible or page, key=lambda r: r[1])
        return FakeResp({"query": {"pages": {"1": {
            "id": 1, "title": title,
            "revisions": [{"revid": chosen[0], "timestamp": chosen[1]}]}}}})


def wiki_calls(fake, **want):
    return [p for u, p in fake.calls
            if u.endswith("/w/api.php") and all(p.get(k) == v for k, v in want.items())]


# ---------------------------------------------------------------------------
# Wikipedia: the no-lookahead gate
# ---------------------------------------------------------------------------

def test_wiki_reads_only_what_was_known():
    fake = FakeHttp()
    r = lab_research.research_as_of("2015-03-15", ["AAPL"],
                                {"names": {"AAPL": "Apple Inc."}},
                                http_get=fake)
    assert "made the iPhone by 2015" in r["AAPL"]
    assert "Vision Pro" not in r["AAPL"]          # that revision came later
    lookup = wiki_calls(fake, rvstarttimestamp="2015-03-15T23:59:59Z")
    assert lookup and lookup[0]["rvdir"] == "older"
    assert "_skips" not in r


def test_page_created_after_the_date_is_skipped():
    fake = FakeHttp()
    r = lab_research.research_as_of("2015-03-15", ["BRK"], http_get=fake)
    assert r["BRK"] is None
    assert "page yet" in r["_skips"]["BRK"]
    # and its content was never even fetched
    assert wiki_calls(fake, revids="2000") == []


def test_missing_page_is_skipped_honestly():
    fake = FakeHttp()
    r = lab_research.research_as_of("2015-03-15", ["NOSUCH"], http_get=fake)
    assert r["NOSUCH"] is None
    assert "no Wikipedia page" in r["_skips"]["NOSUCH"]


def test_content_is_cached_by_revision():
    fake = FakeHttp()
    res = lab_research.Researcher(http_get=fake)
    res("2015-03-15", ["AAPL"], {"names": {"AAPL": "Apple Inc."}})
    res("2015-06-01", ["AAPL"], {"names": {"AAPL": "Apple Inc."}})
    # two lookup calls (one per date), but the 2015 revision's content
    # is fetched exactly once — the second date resolved to the same rev
    assert len(wiki_calls(fake, rvstarttimestamp="2015-03-15T23:59:59Z")) == 1
    assert len(wiki_calls(fake, rvstarttimestamp="2015-06-01T23:59:59Z")) == 1
    assert len(wiki_calls(fake, revids="1000")) == 1


# ---------------------------------------------------------------------------
# arXiv: submittedDate <= D, guaranteed client-side
# ---------------------------------------------------------------------------

ARXIV_MIX = [
    ("The 2014 rate model", "Abstract A", "2014-01-01"),
    ("A paper of 2015-03-15", "Abstract B", "2015-03-15"),
    ("A paper of 2015-03-16", "Abstract C", "2015-03-16"),
    ("A paper of 2016", "Abstract D", "2016-01-01"),
]


def test_arxiv_keeps_only_papers_already_submitted():
    fake = FakeHttp(ranged_atom=atom(ARXIV_MIX))
    r = lab_research.research_as_of("2015-03-15", ["TSM"], http_get=fake)
    assert "The 2014 rate model" in r["TSM"]
    assert "A paper of 2015-03-15" in r["TSM"]      # submitted that day: known
    assert "2015-03-16" not in r["TSM"]             # the next day: future
    assert "A paper of 2016" not in r["TSM"]
    arxiv = [p for u, p in fake.calls if u.startswith(lab_research.ARXIV_URL)]
    assert "submittedDate" in arxiv[0]["search_query"]
    assert "201503152359" in arxiv[0]["search_query"]


def test_arxiv_undated_fallback_still_cannot_peek():
    # the ranged query returns nothing; the undated retry returns a mix —
    # the client-side published check must drop the future entries
    fake = FakeHttp(ranged_atom="", plain_atom=atom(ARXIV_MIX))
    r = lab_research.research_as_of("2015-03-15", ["TSM"], http_get=fake)
    assert "The 2014 rate model" in r["TSM"]
    assert "2015-03-16" not in r["TSM"]
    assert "A paper of 2016" not in r["TSM"]
    arxiv = [p for u, p in fake.calls if u.startswith(lab_research.ARXIV_URL)]
    assert len(arxiv) == 2 and "submittedDate" not in arxiv[1]["search_query"]


# ---------------------------------------------------------------------------
# The budget, the failures, the names
# ---------------------------------------------------------------------------

def test_the_call_cap_stops_all_further_spending():
    fake = FakeHttp()
    res = lab_research.Researcher(call_cap=2, http_get=fake)
    r = res("2015-03-15", ["AAPL", "ZZZ"], {"names": {"AAPL": "Apple Inc."}})
    # AAPL spends the whole budget (1 lookup + 1 content); ZZZ gets none
    assert "made the iPhone by 2015" in r["AAPL"]
    assert r["ZZZ"] is None
    assert "budget" in r["_skips"]["ZZZ"]
    assert len(fake.calls) == 2


def test_http_failures_are_reported_not_fatal():
    fake = FakeHttp(raise_on="Apple")
    r = lab_research.research_as_of("2015-03-15", ["AAPL"],
                                {"names": {"AAPL": "Apple Inc."}},
                                http_get=fake)
    assert r["AAPL"] is None
    assert "failed" in r["_skips"]["AAPL"]
    assert "the web is on fire" in r["_skips"]["AAPL"]


def test_names_map_ticks_to_real_page_titles():
    fake = FakeHttp()
    lab_research.research_as_of("2015-03-15", ["ZZZ"],
                            {"names": {"ZZZ": "Apple Inc."}}, http_get=fake)
    assert wiki_calls(fake, titles="Apple Inc.")


def test_empty_names_and_empty_pages_are_honest():
    fake = FakeHttp()   # wiki exists for Apple Inc. only
    r = lab_research.research_as_of("2015-03-15", ["AAPL"], http_get=fake)
    # no name mapping: the ticker "AAPL" is not a Wikipedia page
    assert r["AAPL"] is None
    assert "no Wikipedia page" in r["_skips"]["AAPL"]


# ---------------------------------------------------------------------------
# The seam: a Researcher plugged into the engine
# ---------------------------------------------------------------------------

def test_researcher_is_the_engine_seam():
    from app import strategy_lab

    fake = FakeHttp()
    px = {"A": {str(date(2015, 3, 11) + timedelta(days=i)): 100.0
                for i in range(20)}}
    p = strategy_lab.make_plan(["A"], frequency="week", research=True,
                               targets={"A": 1.0}, names={"A": "Apple Inc."})
    r = strategy_lab.simulate(p, px, strategy_lab.decide_plan,
                              researcher=lab_research.Researcher(http_get=fake))
    assert r["decisions"] >= 2
    for e in r["log"]:
        assert "made the iPhone by 2015" in e["research"]["A"]
    # research never touches the math
    assert r["equity"] == [100_000.0] * 20
    assert r["trades"] == 1
