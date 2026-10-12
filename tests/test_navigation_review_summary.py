from copy import deepcopy

import pytest

from experiments.retrieval_method.navigation_review_summary import COSTS, DIMENSIONS, analyze


def row(arm, question, category="tutorial", success=True):
    method = arm.split("/")[-1]
    return {"arm": arm, "session": f"{question}--{method}--r1", "item_id": question.split("-p")[0],
        "category": category, "quality_reviewed": True,
        **{d: 1 for d in DIMENSIONS}, **{d: 1 for d in COSTS},
        "qa_success": success, "first_answer_success": success,
        "review": {"gold_points": [{"score": 2}], "extra_errors": []}}


def test_summary_keeps_failed_citations_and_unknown_costs_separate():
    rows = [row(a, q) for a in ("control/no_graph", "native/graph_first") for q in ("Q001-p1", "Q001-p2")]
    rows[-1].update(citation_accuracy=.5, qa_success=False, first_answer_success=False, unknown_usage_attempts=3)
    result = analyze({"sessions": rows, "quality_gate": "reviewed", "protocol_sha256": "frozen"})
    arm = result["arms"]["native/graph_first"]
    assert arm["citation_only_failure"] == ["Q001-p2--r1"]
    assert arm["rewrite_consistency"]["mixed_success"] == ["Q001--r1"]
    assert arm["common_success_with_control"]["questions"] == ["Q001-p1--r1"]
    assert arm["all_session_costs"]["unknown_usage_attempts"] == 4
    assert rows[-1]["qa_success"] is False


def test_summary_rejects_unreviewed_duplicate_and_unpaired_data():
    data = {"sessions": [row("control/no_graph", "Q001-p1"), row("native/graph_first", "Q001-p1")],
        "quality_gate": "reviewed", "protocol_sha256": "frozen"}
    changed = deepcopy(data)
    changed["sessions"][1]["quality_reviewed"] = False
    with pytest.raises(ValueError, match="completed explicit"):
        analyze(changed)
    changed = deepcopy(data)
    changed["sessions"].append(deepcopy(changed["sessions"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        analyze(changed)
    changed = deepcopy(data)
    changed["sessions"][1]["session"] = "Q002-p1--graph_first--r1"
    with pytest.raises(ValueError, match="same question"):
        analyze(changed)


def test_macro_excludes_not_applicable_and_does_not_count_all_failure_as_success_stability():
    rows = [row("control/no_graph", "Q001-p1", success=False), row("control/no_graph", "Q001-p2", success=False),
            row("control/no_graph", "Q002-p1", "manual")]
    rows[0]["case_accuracy"] = 0
    rows[1]["case_accuracy"] = 0
    rows[2]["case_accuracy"] = None
    summary = analyze({"sessions": rows, "quality_gate": "reviewed", "protocol_sha256": "frozen"})
    arm = summary["arms"]["control/no_graph"]
    assert arm["equal_category_macro"]["case_accuracy"] == 0
    assert arm["quality"]["manual"]["case_accuracy"]["n_applicable"] == 0
    assert arm["rewrite_consistency"]["both_or_all_success"] == []
    assert arm["rewrite_consistency"]["all_failure"] == ["Q001--r1"]
