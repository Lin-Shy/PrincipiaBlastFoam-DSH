import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import candidate_case_alias_completion as completion


def test_completion_interface_has_no_question_or_gold_inputs():
    assert "question" not in completion.prepare.__code__.co_varnames
    assert "gold" not in completion.prepare.__code__.co_varnames


def test_completion_selection_is_exhaustive_not_quality_based():
    source = Path(completion.__file__).read_text()
    assert "all and only missing parent chunks" in source
    assert "completion entity coverage gap or overlap" in source
