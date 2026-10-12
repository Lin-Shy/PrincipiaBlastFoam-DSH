"""Repair the Q015 public scope and freeze natural-navigation-qa-v5.

The v4 wording identifies an O2/Sutherland task but does not distinguish the
``blastFoam/reacting`` tutorial from ``blastReactingFoam/reacting``.  Both
tutorials include the same species dictionary and values, while the frozen
annotation requires a different main dictionary.  This repair therefore adds
one natural, public case anchor to all eight variants and asks two independent
Flash reviewers to verify uniqueness and semantic fidelity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_natural_navigation_v2 as natural


MODEL = "deepseek-flash"
FAMILY = "sutherland-included-species-inputs"
PUBLIC_ANCHOR = "blastFoam 求解器的 reacting 教程"
REQUIRED_ANCHOR_PARTS = ("blastFoam", "reacting", "教程")


def wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(raw: bytes | str) -> str:
    if isinstance(raw, str):
        raw = raw.encode()
    return hashlib.sha256(raw).hexdigest()


def rewrite_questions(rows: list[dict]) -> list[str]:
    """Add only the missing public case anchor, preserving each style variant."""
    ordered = sorted(rows, key=lambda row: row["id"])
    if len(ordered) != 8:
        raise ValueError("Q015 repair requires exactly eight variants")
    return [f"在 {PUBLIC_ANCHOR}中，{row['question']}" for row in ordered]


def local_issues(question: str) -> list[str]:
    issues = []
    missing = [part for part in REQUIRED_ANCHOR_PARTS if part not in question]
    if missing:
        issues.append("missing_unique_anchor:" + ",".join(missing))
    if "blastReactingFoam" in question:
        issues.append("wrong_or_contrastive_solver_anchor")
    if "/" in question or "`" in question or "::" in question:
        issues.append("path_or_code_syntax")
    if len(question) < 18 or len(question) > 240:
        issues.append("length_out_of_range")
    return issues


def reviewer_body(annotation: dict, old_rows: list[dict], questions: list[str], reviewer: int) -> dict:
    prompt = {
        "task": "独立审核Q015的8条修复问题是否已唯一限定评分目标，同时保持自然、忠实且不泄漏答案。",
        "reviewer": reviewer,
        "independence": "请独立判断，不假设另一位审核者会纠错。",
        "known_corpus_collision": {
            "problem": (
                "语料中同时存在blastFoam/reacting与blastReactingFoam/reacting；二者包含的"
                "thermo.compressibleGas内容及O2的As、Ts值相同，但主配置文件名与结构不同。"
            ),
            "required_target": "私有标注要求blastFoam/reacting及其phaseProperties主配置。",
            "accepted_public_disambiguation": (
                "中文短语‘blastFoam 求解器的 reacting 教程’是必要且自然的公开场景锚点；"
                "它不是答案值泄漏，也不得因出现该短语而判失败。"
            ),
        },
        "rules": [
            "把每条问题视为没有标题、上一问或题族名的新对话。",
            "每条都必须单独、明确地指向blastFoam求解器的reacting教程，而不是blastReactingFoam求解器的同名教程。",
            "问题应保留旧问题的完整意图：解释Sutherland公式和参数，并沿包含关系定位O2实际参数、主配置位置与物理来源文件。",
            "不得直接陈述私有gold中的公式展开、参数取值、主文件名、字典路径或标准结论。",
            "询问公式、参数含义、实际数值、文件位置和包含关系属于正常检索意图，不是泄漏。",
            "只报告实质的作用域歧义、语义缺失/新增、裸指代或答案泄漏；不要回答问题。",
        ],
        "old_questions": [row["question"] for row in sorted(old_rows, key=lambda row: row["id"])],
        "private_contract": {
            key: annotation.get(key)
            for key in ("intents", "concepts", "cases", "targets", "gold", "allowed", "forbidden", "ambiguity")
        },
        "questions": [{"index": index, "text": question} for index, question in enumerate(questions)],
        "output": {
            "items": [{"index": "0到7", "pass": "布尔值", "issues": ["通过为空；失败列实质问题"]}],
            "all_pass": "仅当8条全部通过时为true",
        },
    }
    return {
        "model": MODEL,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "max_tokens": 3500,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return one valid JSON object only."},
            {"role": "user", "content": wire(prompt)},
        ],
    }


def validate_review(value: object) -> list[dict]:
    if isinstance(value, dict) and isinstance(value.get("output"), dict):
        value = value["output"]
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError("Q015 uniqueness review lacks items")
    items = sorted(value["items"], key=lambda row: int(row["index"]))
    if len(items) != 8 or [int(row["index"]) for row in items] != list(range(8)):
        raise ValueError("Q015 uniqueness review indices differ from 0..7")
    for row in items:
        if row.get("pass") not in (True, False):
            raise ValueError("Q015 uniqueness review pass must be boolean")
        if not isinstance(row.get("issues", []), list):
            raise ValueError("Q015 uniqueness review issues must be a list")
    return items


def reviewed(request: dict, key: str, path: Path) -> list[dict]:
    payload = natural.api_call(request, key, path)
    try:
        return validate_review(natural.response_value(payload))
    except (ValueError, KeyError, TypeError) as error:
        correction = dict(request)
        correction["messages"] = request["messages"] + [
            {"role": "assistant", "content": payload["choices"][0]["message"]["content"]},
            {"role": "user", "content": wire({
                "mechanical_validation_error": str(error)[:240],
                "instruction": "逐条输出index 0到7共8项；不要因格式纠正而改变原语义判断。",
            })},
        ]
        corrected_path = path.with_name(path.stem + "-correction.json")
        corrected = natural.api_call(correction, key, corrected_path)
        return validate_review(natural.response_value(corrected))


def verify_source(source: Path) -> dict:
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("schema") != "natural-navigation-qa-v4":
        raise ValueError("Q015 repair source must be frozen natural-navigation-qa-v4")
    for relative, expected in manifest["artifacts"].items():
        if sha((source / relative).read_bytes()) != expected:
            raise ValueError(f"source dataset drift: {relative}")
    return manifest


def provider_models(output: Path) -> list[str]:
    models = set()
    for path in output.rglob("*.json"):
        value = json.loads(path.read_text())
        if isinstance(value, dict) and value.get("request_sha256") and value.get("status") == "response":
            models.add(value.get("response", {}).get("model"))
    return sorted(models)


def read_api_key(key_file: Path | None, settings_file: Path | None) -> str:
    if key_file is not None:
        key = key_file.read_text().strip()
    else:
        settings = {}
        for line in settings_file.read_text().splitlines():  # type: ignore[union-attr]
            if "=" in line:
                name, value = line.split("=", 1)
                settings[name.strip()] = value.strip()
        key = settings.get("API_KEY", "")
    if not key:
        raise ValueError("DeepSeek API key is empty")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    credential = parser.add_mutually_exclusive_group(required=True)
    credential.add_argument("--key-file", type=Path)
    credential.add_argument("--settings-file", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if output.exists() and (output / "manifest.json").exists():
        raise FileExistsError("frozen v5 dataset already exists")

    source_manifest = verify_source(source)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, output, dirs_exist_ok=True, ignore=shutil.ignore_patterns("manifest.json"))

    dev = json.loads((source / "dev.questions.json").read_text())
    holdout = json.loads((source / "holdout.questions.json").read_text())
    old_rows = [row for row in dev if row["family_id"] == FAMILY]
    if len(old_rows) != 8 or any(row["split"] != "dev" for row in old_rows):
        raise ValueError("Q015 family must contain eight dev variants")
    annotations = json.loads((source / "dev.annotations.json").read_text())
    matches = [row for row in annotations if row["id"] == FAMILY]
    if len(matches) != 1 or matches[0].get("cases") != ["blastFoam/reacting"]:
        raise ValueError("Q015 private target drift")
    annotation = matches[0]
    questions = rewrite_questions(old_rows)
    deterministic = [local_issues(question) for question in questions]
    if any(deterministic):
        raise ValueError(f"deterministic Q015 repair failure: {deterministic}")

    key = read_api_key(args.key_file, args.settings_file)
    reviews = []
    records = output / "repair-records" / FAMILY
    for reviewer in (1, 2):
        request = reviewer_body(annotation, old_rows, questions, reviewer)
        path = records / f"v5-uniqueness-review-{reviewer}-{sha(wire(request))[:12]}.json"
        reviews.append(reviewed(request, key, path))
    failures = [
        {"reviewer": reviewer, "index": int(item["index"]), "issues": item.get("issues", [])}
        for reviewer, review in enumerate(reviews, 1)
        for item in review if item.get("pass") is not True
    ]
    if failures:
        raise RuntimeError(f"Q015 uniqueness review failed: {failures}")

    replacements = {row["id"]: questions[index] for index, row in enumerate(sorted(old_rows, key=lambda row: row["id"]))}
    for row in dev:
        if row["id"] in replacements:
            row["question"] = replacements[row["id"]]
    natural.write(output / "dev.questions.json", dev)
    natural.write(output / "holdout.questions.json", holdout)

    summary_path = output / "repair-summary.json"
    summary = json.loads(summary_path.read_text())
    summary.append({
        "family": FAMILY,
        "reason": "public question did not distinguish two reacting tutorials with identical included O2 values",
        "public_anchor": PUBLIC_ANCHOR,
        "questions": 8,
        "reviewers": 2,
        "all_pass": True,
    })
    natural.write(summary_path, summary)

    models = provider_models(output)
    if models != [MODEL]:
        raise ValueError(f"unexpected provider model identities: {models}")
    artifacts = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.relative_to(output).as_posix()] = sha(path.read_bytes())
    manifest = {
        "schema": "natural-navigation-qa-v5",
        "created_unix_ns": time.time_ns(),
        "model": MODEL,
        "provider_models": models,
        "parent_manifest_sha256": sha((source / "manifest.json").read_bytes()),
        "repair_reason": "Q015 needed a public solver/tutorial anchor to make its frozen main-dictionary target unique",
        "families": 30,
        "variants_per_family": 8,
        "counts": source_manifest["counts"],
        "split_by_family": source_manifest["split_by_family"],
        "corpus": source_manifest["corpus"],
        "generation": {
            "parent_records_retained": len(list((output / "generation-records").rglob("*.json"))),
            "prior_repair_records_retained": len([
                path for path in (output / "repair-records").rglob("*.json")
                if "v5-uniqueness-review" not in path.name
            ]),
            "q015_uniqueness_review_records": len([
                path for path in records.glob("v5-uniqueness-review-*.json")
            ]),
            "q015_double_reviewed": True,
        },
        "artifacts": artifacts,
    }
    natural.write(output / "manifest.json", manifest)
    print(wire({key: manifest[key] for key in ("schema", "provider_models", "counts", "generation", "repair_reason")}))


if __name__ == "__main__":
    main()
