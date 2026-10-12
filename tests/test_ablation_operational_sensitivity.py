import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

from ablation_operational_sensitivity import analyze
from ablation_results import SINGLES


def row(arm, failures=0):
    sessions = []
    for category in ("tutorial", "manual", "cross"):
        for index in range(2):
            terminal = category == "cross" and index < failures
            sessions.append({"category": category,
                             "state": "tested_terminal_failure" if terminal else "reviewed",
                             "quality": {"qa_success": not terminal}})
    return {"arm": arm, "sessions": sessions}


def test_transport_bound_does_not_replace_observed_primary_score():
    reference = {"all_arms_rankable": True, "arms": [row("full_candidate")]}
    ablations = {"all_arms_rankable": True,
                 "arms": [row(arm, 1 if arm == "minus_paths" else 0)
                          for arm in SINGLES.values()]}
    result = analyze(reference, ablations)
    paths = result["components"]["paths"]
    assert result["primary_analysis_changed"] is False
    assert paths["terminal_transport_failures"] == 1
    assert paths["component_effect_full_minus_removed_observed"] == pytest.approx(1 / 6)
    assert paths["component_effect_transport_sensitivity_bounds"] == pytest.approx([0, 1 / 6])


def test_unadmitted_reports_are_rejected():
    with pytest.raises(ValueError, match="admitted"):
        analyze({"all_arms_rankable": False}, {"all_arms_rankable": True})
