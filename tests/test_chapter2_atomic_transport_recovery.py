from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments/retrieval_method"))
import chapter2_augmentation as core
from chapter2_atomic_transport_recovery import clean_stability


def fixture(tmp_path, valid, label):
    root, view = tmp_path / "root", tmp_path / "view"
    questions = tmp_path / "questions.json"
    core.save(questions, [{"id": "Q1", "family_id": "F1"}])
    core.save(root / "protocol.json", {"inputs": {"test_questions": {"path": str(questions)}}})
    core.save(root / "evaluation_only/review-sample.json", {"families": ["F1"]})
    record = {"judgment": {"requirements": [{"assessment": label}], "citations": [], "extra_errors": [], "extra_errors_uncertain": False},
              "atomic_items": [{"valid": valid}]}
    for stage in ("scores", "regrades"):
        for repeat in range(1, 4):
            for arm in core.ARMS:
                core.save(view / "evaluation_only" / stage / "test/Q1" / f"r{repeat}" / arm / "score.json", record)
    return root, view


def test_identical_program_fallback_unknowns_are_not_judge_agreement(tmp_path):
    root, view = fixture(tmp_path, False, "uncertain")
    result = clean_stability(core, root, view)
    assert result["planned"] == 12
    assert result["invalid_item_pairs"] == 12
    assert result["determinate_pairs"] == 0
    assert result["determinate_agreement"] is None


def test_valid_but_semantically_uncertain_pairs_stay_separate(tmp_path):
    root, view = fixture(tmp_path, True, "uncertain")
    result = clean_stability(core, root, view)
    assert result["schema_valid_pairs"] == 12
    assert result["uncertain_label_pairs"] == 12
    assert result["determinate_pairs"] == 0


def test_determinate_pair_agreement_retains_fixed_full_denominator(tmp_path):
    root, view = fixture(tmp_path, True, "missing")
    result = clean_stability(core, root, view)
    assert result["planned"] == 12
    assert result["determinate_pairs"] == 12
    assert result["same_determinate_labels"] == 12
    assert result["determinate_agreement"] == 1
