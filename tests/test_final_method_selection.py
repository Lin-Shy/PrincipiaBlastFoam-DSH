import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

from final_method_selection import require_registered_input, require_report_protocol, select


ARMS = [
    "full_candidate", "minus_role_scope", "minus_conditional_bilateral",
    "minus_semantic_recall", "minus_paths", "minus_evidence_groups",
    "minus_gap_strategy", "minus_claim_verification",
    "minus_role_scope_x_conditional_bilateral", "minus_paths_x_evidence_groups",
]


def quality_row(arm, strict, citation, cross, method="retrieval_first"):
    return {"arm": arm, "method": method, "strict_success_macro": strict,
            "metrics": {"citation_accuracy": {"macro_over_applicable_categories": citation},
                        "cross_source_completeness": {"macro_over_applicable_categories": cross}}}


def costs(arms, method="retrieval_first"):
    return {"arms": [{"arm": arm, "method": method,
                       "reported_usage": {"total_tokens": 1000 + index}}
                      for index, arm in enumerate(arms)]}


def registration():
    return {"model": "deepseek-flash", "candidate_eligible_arms": ARMS,
            "selection_rule": {"switch_from_incumbent_only_if": {
                "strict_success_macro_margin_at_least": 0.02,
                "citation_accuracy_margin_at_least": -0.02,
                "cross_source_completeness_margin_at_least": -0.02}}}


def reports(full=(0.91, 0.95, 0.93)):
    baseline = {"all_arms_rankable": True,
                "arms": [quality_row("GN", 0.88, 0.96, 0.94, "graph_first")]}
    candidate = {"all_arms_rankable": True,
                 "arms": [quality_row("full_candidate", *full)]}
    ablation = {"all_arms_rankable": True,
                "arms": [quality_row(arm, 0.80, 0.97, 0.95) for arm in ARMS[1:]]}
    return baseline, costs(["GN"], "graph_first"), candidate, costs(["full_candidate"]), \
        ablation, costs(ARMS[1:])


def test_candidate_replaces_incumbent_only_after_all_registered_margins_pass():
    _, candidates, selected = select(registration(), *reports())
    assert selected["arm"] == "full_candidate"
    assert candidates[0]["eligible_to_replace_incumbent"] is True


def test_incumbent_is_retained_for_small_development_gain():
    _, candidates, selected = select(registration(), *reports((0.89, 0.95, 0.93)))
    assert selected["arm"] == "GN"
    assert candidates[0]["eligible_to_replace_incumbent"] is False


def test_unadmitted_ablation_is_rejected_before_selection():
    values = list(reports())
    values[4]["all_arms_rankable"] = False
    with pytest.raises(ValueError, match="ablation development report"):
        select(registration(), *values)


def test_registered_input_rejects_path_substitution_even_for_valid_json(tmp_path):
    first = tmp_path / "first.json"; second = tmp_path / "second.json"
    first.write_text("{}\n"); second.write_text("{}\n")
    import hashlib
    bound = {"development_artifacts": {"quality": {
        "path": str(first), "sha256": hashlib.sha256(first.read_bytes()).hexdigest()}}}
    require_registered_input(bound, "quality", first)
    with pytest.raises(ValueError, match="registered quality"):
        require_registered_input(bound, "quality", second)


def test_report_must_bind_registered_protocol():
    require_report_protocol({"protocol_sha256": "expected"}, "expected", "quality")
    with pytest.raises(ValueError, match="registered run protocol"):
        require_report_protocol({"protocol_sha256": "other"}, "expected", "quality")
