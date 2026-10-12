import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "experiments/retrieval_method/natural_question_context_audit.py"
SPEC = importlib.util.spec_from_file_location("natural_question_context_audit", MODULE)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_validate_accepts_complete_eight_item_review():
    rows = [
        {"index": index, "pass": True, "issue": "", "public_anchors_found": ["anchor"]}
        for index in range(8)
    ]
    assert audit.validate({"items": list(reversed(rows)), "all_pass": True}) == rows


def test_validate_rejects_failure_without_reason():
    rows = [
        {"index": index, "pass": index != 3, "issue": "", "public_anchors_found": []}
        for index in range(8)
    ]
    try:
        audit.validate({"items": rows, "all_pass": False})
    except ValueError as error:
        assert "must report issue" in str(error)
    else:
        raise AssertionError("invalid failed review accepted")


def test_validate_unwraps_echoed_output_contract():
    rows = [
        {"index": index, "pass": True, "issue": "", "public_anchors_found": []}
        for index in range(8)
    ]
    assert audit.validate({"independence": "x", "output": {"items": rows, "all_pass": True}}) == rows


def test_read_api_key_supports_project_settings_file(tmp_path):
    settings = tmp_path / "llm-setting.txt"
    settings.write_text("API_KEY = secret-value\nmodel = deepseek-flash\n")
    assert audit.read_api_key(None, settings) == "secret-value"
