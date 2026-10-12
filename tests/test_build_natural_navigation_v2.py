import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "experiments/retrieval_method/build_natural_navigation_v2.py"
SPEC = importlib.util.spec_from_file_location("build_natural_navigation_v2", MODULE)
assert SPEC and SPEC.loader
natural = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(natural)


def test_family_split_is_deterministic_balanced_and_isolated():
    rows = [
        {"id": f"Q{category}{index}", "family": f"{category}-{index}", "category": category}
        for category in ("tutorial", "manual", "cross") for index in range(10)
    ]
    first = natural.split_families(rows)
    second = natural.split_families(list(reversed(rows)))
    assert first == second
    assert sum(split == "dev" for split in first.values()) == 18
    assert sum(split == "holdout" for split in first.values()) == 12


def test_deterministic_leak_scan_rejects_case_and_path_but_accepts_natural_need():
    annotation = {
        "cases": ["blastFoam/freeField"],
        "targets": ["system/controlDict::writeInterval"],
        "evidence": [{"path": "tutorials/blastFoam/freeField/system/controlDict"}],
    }
    leaked = "请查一下blastFoam/freeField里的controlDict。"
    assert natural.deterministic_issues(leaked, annotation)
    clean = "我想减少整个流场写到磁盘的频率，但保留计算过程中的必要结果，应该先查哪些设置？"
    assert natural.deterministic_issues(clean, annotation) == []


def test_generic_material_or_physics_word_is_not_treated_as_repository_identifier():
    annotation = {
        "cases": ["blastFoam/twoChargeDetonation"],
        "targets": ["constant/phaseProperties::phases/RDX"],
        "evidence": [{"path": "tutorials/blastFoam/twoChargeDetonation/constant/phaseProperties"}],
    }
    question = "我需要比较RDX和另一种炸药在不同相中的配置思路，应该从哪些资料查起？"
    assert natural.deterministic_issues(question, annotation) == []


def test_review_contract_requires_exact_indices():
    rows = [{"index": index, "pass": True, "issues": []} for index in range(8)]
    assert natural.validate_review({"items": list(reversed(rows)), "all_pass": True}) == rows


def test_flash_json_decoder_repairs_stray_quote_after_numeric_index():
    malformed = '{"items":[{"index":5","pass":true,"issues":[]}]}'
    assert natural.decode_json(malformed)["items"][0]["index"] == 5
