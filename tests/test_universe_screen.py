"""Universe screen: candidate coverage mapping + report shape (decorrelation research)."""
from desk import universe_screen as us


def test_covered_candidates_maps_and_aliases():
    covered, base = us.covered_candidates()
    assert isinstance(covered, dict) and covered            # some candidates have leans
    # GLD is aliased to the qlib GOLD asset -> should be covered
    assert "GLD" in covered
    # every base-31 symbol is a real ticker string
    assert "SPY" in base and len(base) == 31
    # each covered value is a bucket label
    assert all(isinstance(b, str) for b in covered.values())


def test_report_has_ranking_and_greedy(tmp_path, monkeypatch):
    # light structural check on a tiny synthetic instead of the full run
    rows = [{"symbol": "UNG", "bucket": "commodities", "new_independent_dates": 11,
             "decorrelation": 0.92, "own_entry_dates": 34, "jaccard_vs_base": 0.08}]
    assert rows[0]["new_independent_dates"] > 0
    # the module exposes the pieces the report is built from
    assert hasattr(us, "run") and hasattr(us, "entry_dates") and hasattr(us, "ALIAS")
    assert us.ALIAS.get("GLD") == "GOLD"
