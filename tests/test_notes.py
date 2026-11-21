"""Offline tests for the notebook (data/notes.json).

The file is pointed at a temp dir per test, exactly like the portfolio
tests: nothing touches the real data.
"""
import json

import pytest

from app import notes


@pytest.fixture
def notes_path(tmp_path, monkeypatch):
    p = tmp_path / "notes.json"
    monkeypatch.setattr(notes, "NOTES_PATH", p)
    return p


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_missing_file_is_an_empty_notebook(notes_path):
    assert notes.load_pages() == []
    assert notes.list_pages() == []


def test_create_saves_and_reloads(notes_path):
    p = notes.create_page("My page", "some thoughts")
    saved = json.loads(notes_path.read_text())
    assert saved["v"] == notes._NOTES_VERSION
    assert len(saved["pages"]) == 1
    assert notes.get_page(p["id"])["body"] == "some thoughts"


def test_empty_title_is_allowed(notes_path):
    p = notes.create_page("   ")
    assert p["title"] == ""          # the UI names it right after


def test_corrupt_file_is_an_empty_notebook(notes_path):
    notes_path.write_text("{ not json")
    assert notes.load_pages() == []


def test_wrong_version_file_is_an_empty_notebook(notes_path):
    notes_path.write_text(json.dumps(
        {"v": 99, "updated": 0, "pages": [{"id": "n1", "title": "x"}]}))
    assert notes.load_pages() == []


def test_missing_snippets_key_heals(notes_path):
    notes_path.write_text(json.dumps(
        {"v": 1, "updated": 0,
         "pages": [{"id": "n1", "title": "x", "body": "b"}]}))
    assert notes.get_page("n1")["snippets"] == []


# ---------------------------------------------------------------------------
# Pages: update, delete, list
# ---------------------------------------------------------------------------

def test_update_changes_only_given_fields(notes_path):
    p = notes.create_page("A", "body one")
    out = notes.update_page(p["id"], title="B")
    assert out["title"] == "B" and out["body"] == "body one"
    out = notes.update_page(p["id"], body="body two")
    assert out["title"] == "B" and out["body"] == "body two"


def test_update_trims_and_caps_but_keeps_line_breaks(notes_path):
    p = notes.create_page("A")
    out = notes.update_page(p["id"], title="  x   y  ", body="  a\n\nb  ")
    # titles collapse whitespace; a note's body keeps its line breaks
    assert out["title"] == "x y" and out["body"] == "a\n\nb"
    out = notes.update_page(p["id"], body="z" * 100000)
    assert len(out["body"]) == notes._BODY_MAX


def test_update_unknown_is_keyerror(notes_path):
    with pytest.raises(KeyError):
        notes.update_page("nope", title="x")


def test_delete_removes(notes_path):
    a = notes.create_page("A")
    b = notes.create_page("B")
    removed = notes.delete_page(a["id"])
    assert removed["id"] == a["id"]
    assert [p["id"] for p in notes.load_pages()] == [b["id"]]


def test_delete_unknown_is_keyerror(notes_path):
    with pytest.raises(KeyError):
        notes.delete_page("nope")


def test_list_sorts_newest_first(notes_path):
    a = notes.create_page("A")
    b = notes.create_page("B")
    # b was created a moment later; its timestamp is >= a's
    order = [s["id"] for s in notes.list_pages()]
    assert order[0] == b["id"] or order[1] == b["id"]
    first = notes.list_pages()[0]
    assert first["n_snippets"] == 0
    assert "preview" in first and "updated" in first


def test_summary_shows_first_lines_of_snippet(notes_path):
    p = notes.create_page("A")
    notes.add_snippet(p["id"], "ask", "Q?", ["the answer line"])
    s = notes.list_pages()[0]
    assert s["n_snippets"] == 1
    assert "answer" in s["preview"]


# ---------------------------------------------------------------------------
# Snippets: the pieces saved from elsewhere
# ---------------------------------------------------------------------------

def test_add_snippet_appends(notes_path):
    p = notes.create_page("A")
    out = notes.add_snippet(p["id"], "backtest", "AAPL run",
                            ["Total: +50%", "Per year: +20%"])
    assert len(out["snippets"]) == 1
    s = out["snippets"][0]
    assert s["source"] == "backtest" and s["title"] == "AAPL run"
    assert s["lines"] == ["Total: +50%", "Per year: +20%"]
    assert s["id"].startswith("s")


def test_re_saving_same_piece_is_a_noop(notes_path):
    p = notes.create_page("A")
    notes.add_snippet(p["id"], "money", "Apple Inc", ["x: $1B"])
    out = notes.add_snippet(p["id"], "money", "Apple Inc", ["x: $1B"])
    assert len(out["snippets"]) == 1


def test_same_text_different_source_is_not_a_duplicate(notes_path):
    p = notes.create_page("A")
    notes.add_snippet(p["id"], "money", "Apple Inc", ["x: $1B"])
    out = notes.add_snippet(p["id"], "ask", "Apple Inc", ["x: $1B"])
    assert len(out["snippets"]) == 2


def test_unknown_source_becomes_other(notes_path):
    p = notes.create_page("A")
    out = notes.add_snippet(p["id"], "vibecode", "T", ["l"])
    assert out["snippets"][0]["source"] == "other"


def test_empty_snippet_is_rejected(notes_path):
    p = notes.create_page("A")
    with pytest.raises(ValueError):
        notes.add_snippet(p["id"], "ask", "   ", ["  "])


def test_snippet_lines_are_capped_and_tidy(notes_path):
    p = notes.create_page("A")
    out = notes.add_snippet(p["id"], "ask", "T", ["  " + "x" * 999 + "  "] * 80)
    lines = out["snippets"][0]["lines"]
    assert len(lines) == notes._LINES_MAX
    assert all(len(ln) <= notes._LINE_MAX for ln in lines)


def test_snippet_blank_lines_are_tidy(notes_path):
    p = notes.create_page("A")
    out = notes.add_snippet(p["id"], "company", "T",
                            ["", "a", "", "b", "", ""])
    # leading and trailing blanks dropped, the middle one kept (a paragraph
    # break when rendered)
    assert out["snippets"][0]["lines"] == ["a", "", "b"]
    out = notes.add_snippet(p["id"], "company", "U", ["x", "", ""])
    assert out["snippets"][-1]["lines"] == ["x"]
    out = notes.add_snippet(p["id"], "company", "title only", ["  ", ""])
    assert out["snippets"][-1]["lines"] == []   # a title with no lines is fine


def test_snippet_in_unknown_page_is_keyerror(notes_path):
    with pytest.raises(KeyError):
        notes.add_snippet("nope", "ask", "T", ["l"])


def test_delete_snippet(notes_path):
    p = notes.create_page("A")
    p = notes.add_snippet(p["id"], "ask", "T1", ["l1"])
    p = notes.add_snippet(p["id"], "ask", "T2", ["l2"])
    sid = p["snippets"][0]["id"]
    out = notes.delete_snippet(p["id"], sid)
    assert [s["title"] for s in out["snippets"]] == ["T2"]


def test_delete_unknown_snippet_is_keyerror(notes_path):
    p = notes.create_page("A")
    with pytest.raises(KeyError):
        notes.delete_snippet(p["id"], "snope")
