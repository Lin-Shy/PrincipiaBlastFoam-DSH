from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_local_full_review_gate import source_release_args


def test_controller_billing_output_is_mapped_to_original_worker_score_root():
    proof=dict(prepared_launch_base_command=['python','controller.py','--stage','grading',
        '--output','formal_scores/billing-executions/run1','--score-output','formal_scores',
        '--review-pack','pack_113','--resources','resources.json'])
    args=source_release_args(proof)
    assert args.output==Path('formal_scores') and args.score_output==Path('formal_scores')
    assert args.review_pack==Path('pack_113') and args.resources==Path('resources.json')
    assert args.stage=='grading'


def test_missing_registered_score_root_cannot_fall_back_to_billing_directory():
    proof=dict(prepared_launch_base_command=['python','controller.py','--output','billing'])
    with pytest.raises(AttributeError):source_release_args(proof)
