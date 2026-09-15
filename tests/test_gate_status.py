import json

from desk import gate_status


def test_missing_scorecard_fails_safe(tmp_path):
    status = gate_status.load_gate_status(tmp_path / "missing.json")
    assert status["ok"] is False
    assert set(status["strategies"].values()) == {"not_cleared"}


def test_matching_scorecard_applies_only_explicit_passes(tmp_path):
    path = tmp_path / "scorecard.json"
    path.write_text(json.dumps({
        "experiment_id": "options_gate_v1",
        "spec_fingerprint": gate_status.spec_fingerprint(),
        "generated_at": "2026-07-22T12:00:00+00:00",
        "strategies": {
            "short_put_csp": {"gate": {"passes": True}},
            "short_put_spread": {"gate": {"passes": False}},
        },
    }), encoding="utf-8")
    status = gate_status.load_gate_status(path)
    assert status["ok"] is True
    assert status["strategies"]["short_put_csp"] == "cleared"
    assert status["strategies"]["short_put_spread"] == "not_cleared"
    assert status["strategies"]["jade_lizard"] == "not_cleared"


def test_mismatched_spec_never_clears(tmp_path):
    path = tmp_path / "scorecard.json"
    path.write_text(json.dumps({
        "experiment_id": "options_gate_v1",
        "spec_fingerprint": "old-spec",
        "strategies": {"short_put_csp": {"gate": {"passes": True}}},
    }), encoding="utf-8")
    assert gate_status.load_gate_status(path)["strategies"]["short_put_csp"] == "not_cleared"


def test_apply_to_ticket_does_not_mutate_source(tmp_path):
    source = {"candidates": [{"strategy": "short_put_csp", "gate": "not_cleared"}]}
    enriched = gate_status.apply_to_ticket(source, tmp_path / "missing.json")
    enriched["candidates"][0]["gate"] = "changed"
    assert source["candidates"][0]["gate"] == "not_cleared"
