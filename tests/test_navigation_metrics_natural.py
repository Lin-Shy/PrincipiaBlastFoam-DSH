import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import navigation_metrics as metrics


def test_natural_v2_review_uses_frozen_nine_dimensions():
    seen = {"source": {"1": "value 1;"}}
    annotation = {
        "gold": ["value is 1"], "concepts": [], "cases": [], "targets": [],
        "category": "tutorial", "ambiguity": [],
    }
    row = {
        "answer_sha256": "a", "trace_sha256": "t", "annotation_sha256": "g",
        "status": "complete", "citation_range_checks": [{"valid_seen_range": True}],
    }
    dimensions = {name: None for name in metrics.REVIEW_DIMENSIONS}
    dimensions.update(required_evidence_recall=1, citation_accuracy=1, evidence_status_accuracy=1)
    review = {
        "answer_sha256": "a", "trace_sha256": "t", "annotation_sha256": "g",
        "reviewer": "fixture", "gold_points": [{
            "index": 0, "score": 2, "reason": "supported",
            "support": [{"path": "source", "start": 1, "end": 1, "quote": "value 1;"}],
        }],
        "dimensions": dimensions,
        "citations": [{"index": 0, "supported": True, "reason": "supported"}],
        "extra_errors": [],
    }
    metrics.merge_review(row, review, annotation, {"schema": "natural-navigation-scoring-v2"}, seen)
    assert row["qa_success"] is True
    assert row["answer_accuracy"] == 1
