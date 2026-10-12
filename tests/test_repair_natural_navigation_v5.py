import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "experiments/retrieval_method/repair_natural_navigation_v5.py"
SPEC = importlib.util.spec_from_file_location("repair_natural_navigation_v5", MODULE)
assert SPEC and SPEC.loader
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


def rows():
    return [
        {"id": f"Q015-n{index}", "question": f"第{index}种自然问法需要查询氧气黏度参数。"}
        for index in range(1, 9)
    ]


def test_rewrite_adds_unique_public_anchor_and_preserves_original_question():
    old = rows()
    rewritten = repair.rewrite_questions(list(reversed(old)))
    assert len(rewritten) == 8
    for index, question in enumerate(rewritten):
        assert repair.PUBLIC_ANCHOR in question
        assert question.endswith(old[index]["question"])
        assert repair.local_issues(question) == []


def test_local_check_rejects_ambiguous_or_wrong_solver_anchor():
    assert "missing_unique_anchor:blastFoam" in repair.local_issues(
        "在 reacting 教程中，请查询氧气黏度随温度变化时使用的两个参数。"
    )
    assert "wrong_or_contrastive_solver_anchor" in repair.local_issues(
        "请比较 blastFoam 与 blastReactingFoam 的 reacting 教程中氧气黏度参数。"
    )


def test_validate_review_requires_all_eight_indices():
    valid = [{"index": index, "pass": True, "issues": []} for index in range(8)]
    assert repair.validate_review({"items": list(reversed(valid)), "all_pass": True}) == valid
    try:
        repair.validate_review({"items": valid[:-1], "all_pass": True})
    except ValueError as error:
        assert "0..7" in str(error)
    else:
        raise AssertionError("incomplete review accepted")


def test_read_api_key_supports_project_settings_file(tmp_path):
    settings = tmp_path / "llm-setting.txt"
    settings.write_text("API_KEY = secret-value\n\nBASE_URL = https://example.invalid\n")
    assert repair.read_api_key(None, settings) == "secret-value"
