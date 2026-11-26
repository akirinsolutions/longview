"""The save file: one plain-text download, everything the app holds."""
from app import savefile, vault


def _seed():
    vault.write_section("portfolio", {
        "v": 1, "updated": 1,
        "positions": [
            {"ticker": "AAPL", "name": "Apple Inc.", "shares": 12,
             "cost_basis": 150.0, "purchase_date": "2026-01-15", "note": "long"},
            {"ticker": "CUSTOM-x", "kind": "custom", "name": "Pets",
             "shares": 1, "cost_basis": 5000, "price": 5200,
             "currency": "USD", "purchase_date": ""},
        ]})
    vault.write_section("risk", {"v": 1, "updated": 1,
                                 "moves": {"AAPL": 12.5, "MSFT": -5.0}})
    vault.write_section("notes", {"v": 1, "updated": 1, "pages": [
        {"id": "n1", "title": "My thesis", "body": "Hold and hope.",
         "created": 1732012345, "snippets": [
             {"source": "money", "title": "Top move", "lines": ["AAPL +12%", "next"]},
         ]}]})
    vault.write_section("roster", {"v": 1, "updated": 1, "funds": [
        {"key": "berkshire", "name": "Berkshire Hathaway",
         "manager": "Warren Buffett", "cik": 1067983}]})
    vault.write_section("research", {"v": 1, "updated": 1, "reports": [
        {"id": "r1", "title": "Credit risk", "goal": "how is credit risk priced",
         "summary": "A summary.", "body": "The body of the report.",
         "created": "2026-11-01", "sources": ["wiki", "arxiv"]}]})


def test_renders_everything_as_plain_text():
    _seed()
    text = savefile.render()
    assert "Exported:" in text
    # Portfolio
    assert "AAPL" in text and "Apple Inc." in text and "12.00 sh" in text
    assert "cost 150.00/share" in text and "bought 2026-01-15" in text
    assert "CUSTOM-x" in text and "(custom)" in text
    # Risk
    assert "AAPL  +12.5%" in text and "MSFT  -5.0%" in text
    # Notes
    assert "## My thesis" in text and "Hold and hope." in text
    assert "saved piece (money) — Top move" in text
    # Roster
    assert "Berkshire Hathaway" in text and "Warren Buffett" in text
    assert "CIK 1067983" in text
    # Research
    assert "## Credit risk" in text and "how is credit risk priced" in text
    assert "sources: 2" in text
    # No JSON markers — it's plain text
    assert "{" not in text


def test_empty_vault_still_renders_the_skeleton():
    text = savefile.render(vault_dict=vault.load())
    assert "Nothing saved" in text
    assert "No scenario yet" in text
    assert "No note pages" in text
    assert "No research reports" in text
    assert "No followed funds" in text
    assert "ECONOMY TREE" in text


def test_save_file_has_a_reason_line():
    text = savefile.render()
    assert "plain text" in text.lower()
    assert "JSON" in text  # honest about which file is importable
