import json
from pathlib import Path

import dev_quality_error_analysis as analysis


def _session(question_id, family, success, answer, citation, recall):
    return {
        "question_id": question_id,
        "family": family,
        "category": "cross",
        "quality": {
            "qa_success": success,
            "first_answer_success": success,
            "answer_accuracy": answer,
            "citation_accuracy": citation,
            "required_evidence_recall": recall,
            "cross_source_completeness": recall,
            "concept_accuracy": answer,
        },
    }


def test_analysis_selects_strongest_graph_and_buckets_failures(tmp_path: Path):
    path = tmp_path / "quality.json"
    document = {
        "all_arms_rankable": True,
        "arms": [
            {
                "arm": "native",
                "strict_success_macro": 0.25,
                "sessions": [_session("Q1", "family", False, 0.5, 1, 0.5)],
            },
            {
                "arm": "text_adapter",
                "strict_success_macro": 0.5,
                "sessions": [_session("Q1", "family", True, 1, 1, 1)],
            },
            {
                "arm": "principia_index_free",
                "strict_success_macro": 0,
                "sessions": [_session("Q1", "family", False, 1, 0.5, 1)],
            },
        ],
    }
    path.write_text(json.dumps(document))

    result = analysis.analyse(path)

    assert result["strongest_graph_arm"] == "text_adapter"
    assert result["candidate_failure_buckets"] == {
        "content_complete_but_strict_support_failed": 1
    }
    assert result["families"][0]["candidate_minus_strongest_graph"] == -1
    assert result["candidate_deficient_dimensions"]["citation_accuracy"] == 1


def test_analysis_rejects_unrankable_document(tmp_path: Path):
    path = tmp_path / "quality.json"
    path.write_text(json.dumps({"all_arms_rankable": False}))

    try:
        analysis.analyse(path)
    except ValueError as error:
        assert "not fully rankable" in str(error)
    else:
        raise AssertionError("expected ValueError")
