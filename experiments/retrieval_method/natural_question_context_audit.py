"""Audit whether every natural benchmark question is answerable without hidden context."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_natural_navigation_v2 as natural


MODEL = "deepseek-flash"
RULES = [
    "把每条问题视为单独发送的新对话；不得假设标题、上一问、题族名或私有标注对回答者可见。",
    "回答者已由系统告知检索范围固定为本项目的blastFoam手册与教程语料；问题不必重复软件名、仓库名或‘手册/教程’字样。",
    "在上述固定语料范围内，问题必须公开说明足以定位所问对象的自然场景、材料、功能或比较对象。",
    "若自然功能描述在固定语料内已经能定位唯一案例（例如运动锥体、反应颗粒或大气初始化），不能仅因缺少准确案例名而判失败。",
    "经固定语料目录清点，‘映射式三维建筑’唯一指向映射分阶段建筑示例；不得仅因未写内部案例名而判失败，应结合阶段选择、轴对称切换、名称绑定和调用顺序等正文意图审核。",
    "若私有标注cases为空，说明这是通用手册题；此时明确的功能或概念描述本身即可定位，不得强求案例或材料名。",
    "用户可以用唯一的性质或作用询问未知术语，例如‘能处理接触波的通量方法’；不得反过来要求用户先说出待查询的方法名。",
    "问题中列出的工程目标、设置角色和约束本身都是公开锚点，应结合完整正文判断，不能只搜索案例专名。",
    "准确仓库路径和内部案例标识可以隐藏，但必须换成可理解且可区分的自然描述。",
    "若问题只说‘这两个示例’、‘上述案例’、‘它们’等，而正文没有先给出所指对象，必须判失败。",
    "不得因为私有标注给出了cases、targets或gold，就替问题补齐缺失上下文。",
    "只审核独立可回答性、对象定位和意图完整性；不要回答问题，也不要披露gold。",
]


def wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def load_rows(dataset: Path) -> tuple[list[dict], list[dict]]:
    questions = []
    annotations = []
    for split in ("dev", "holdout"):
        questions.extend(json.loads((dataset / f"{split}.questions.json").read_text()))
        annotations.extend(json.loads((dataset / f"{split}.annotations.json").read_text()))
    return questions, annotations


def body(annotation: dict, questions: list[dict], reviewer: int) -> dict:
    prompt = {
        "task": "逐条审核自然语言检索问题在没有任何对话上下文时是否仍可独立回答。",
        "reviewer": reviewer,
        "independence": "独立判断，不假设另一位审核者会纠错。",
        "rules": RULES,
        "private_contract_for_comparison_only": {
            key: annotation.get(key)
            for key in ("category", "cases", "intents", "concepts", "targets", "gold", "ambiguity")
        },
        "questions": [{"index": index, "text": row["question"]} for index, row in enumerate(questions)],
        "output": {
            "items": [{
                "index": "0到7的整数", "pass": "布尔值",
                "issue": "通过为空字符串；失败时用一句话说明缺失的公开上下文",
                "public_anchors_found": ["问题正文中实际出现的自然定位锚点"],
            }],
            "all_pass": "仅当八条全部通过时为true",
        },
    }
    return {
        "model": MODEL, "temperature": 0, "thinking": {"type": "disabled"},
        "max_tokens": 4000, "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return one valid JSON object only."},
            {"role": "user", "content": wire(prompt)},
        ],
    }


def validate(value: object) -> list[dict]:
    if isinstance(value, dict) and isinstance(value.get("output"), dict):
        value = value["output"]
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError("context audit lacks items")
    items = sorted(value["items"], key=lambda row: int(row["index"]))
    if len(items) != 8 or [int(row["index"]) for row in items] != list(range(8)):
        raise ValueError("context audit indices differ from 0..7")
    for row in items:
        if row.get("pass") not in (True, False):
            raise ValueError("context audit pass must be boolean")
        if row["pass"] and row.get("issue") not in (None, ""):
            raise ValueError("passing context audit must not report issue")
        if not row["pass"] and not str(row.get("issue", "")).strip():
            raise ValueError("failing context audit must report issue")
        if not isinstance(row.get("public_anchors_found", []), list):
            raise ValueError("public_anchors_found must be a list")
    return items


def reviewed(request: dict, key: str, record: Path) -> list[dict]:
    payload = natural.api_call(request, key, record)
    try:
        return validate(natural.response_value(payload))
    except (ValueError, KeyError, TypeError) as error:
        correction = dict(request)
        correction["messages"] = request["messages"] + [
            {"role": "assistant", "content": payload["choices"][0]["message"]["content"]},
            {"role": "user", "content": wire({
                "mechanical_validation_error": str(error)[:240],
                "instruction": (
                    "上份审核的JSON格式或结构无效。请保持原语义判断，逐条输出index 0到7共8项；"
                    "不要为了通过而改变判断。"
                ),
            })},
        ]
        corrected_record = record.with_name(record.stem + "-correction.json")
        corrected = natural.api_call(correction, key, corrected_record)
        return validate(natural.response_value(corrected))


def audit_family(annotation: dict, rows: list[dict], key: str, output: Path) -> dict:
    results = []
    for reviewer in (1, 2):
        request = body(annotation, rows, reviewer)
        record = output / "records" / annotation["id"] / f"reviewer-{reviewer}.json"
        results.append(reviewed(request, key, record))
    if any(results[0][index]["pass"] != results[1][index]["pass"] for index in range(8)):
        request = body(annotation, rows, 3)
        record = output / "records" / annotation["id"] / "reviewer-3.json"
        results.append(reviewed(request, key, record))
    failures = []
    for index, row in enumerate(rows):
        votes = sum(result[index]["pass"] is True for result in results)
        rejected = [
            {"reviewer": reviewer + 1, "issue": result[index]["issue"],
             "public_anchors_found": result[index].get("public_anchors_found", [])}
            for reviewer, result in enumerate(results) if result[index]["pass"] is not True
        ]
        if votes <= len(results) // 2:
            failures.append({"id": row["id"], "question": row["question"], "rejections": rejected})
    return {"family": annotation["id"], "split": annotation["split"], "failures": failures,
            "reviewer_count": len(results), "all_pass": not failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    credential = parser.add_mutually_exclusive_group(required=True)
    credential.add_argument("--key-file", type=Path)
    credential.add_argument("--settings-file", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    questions, annotations = load_rows(dataset)
    if len(questions) != 240 or len(annotations) != 30:
        raise ValueError("expected 240 questions and 30 annotations")
    grouped = {}
    for row in questions:
        grouped.setdefault(row["family_id"], []).append(row)
    if any(len(rows) != 8 for rows in grouped.values()):
        raise ValueError("each family must contain eight questions")
    protocol = {
        "schema": "natural-question-context-audit-v1", "model": MODEL, "rules": RULES,
        "dataset_manifest_sha256": sha(dataset / "manifest.json"),
        "dev_questions_sha256": sha(dataset / "dev.questions.json"),
        "holdout_questions_sha256": sha(dataset / "holdout.questions.json"),
        "reviewers_per_family": "two independent; third independent reviewer on any item disagreement",
        "question_context": "fixed blastFoam manual/tutorial corpus only; no prior question or family title",
    }
    protocol_path = output / "protocol.json"
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
        raise ValueError("context audit protocol drift")
    natural.write(protocol_path, protocol)
    key = read_api_key(args.key_file, args.settings_file)
    results = []
    by_id = {row["id"]: row for row in annotations}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {
            pool.submit(audit_family, by_id[family], sorted(rows, key=lambda row: row["id"]), key, output): family
            for family, rows in grouped.items()
        }
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            print("PASS" if result["all_pass"] else "FAIL", result["family"], len(result["failures"]), flush=True)
    records = list((output / "records").glob("*/*.json"))
    models = sorted({json.loads(path.read_text())["response"].get("model") for path in records})
    summary = {
        "schema": "natural-question-context-audit-summary-v1", "created_unix_ns": time.time_ns(),
        "protocol_sha256": sha(protocol_path), "families": len(results), "questions": len(questions),
        "provider_models": models, "all_pass": all(row["all_pass"] for row in results),
        "failed_families": sum(not row["all_pass"] for row in results),
        "failed_questions": sum(len(row["failures"]) for row in results),
        "results": sorted(results, key=lambda row: row["family"]),
    }
    if models != [MODEL]:
        raise ValueError(f"unexpected provider models: {models}")
    natural.write(output / "summary.json", summary)
    print(wire({key: summary[key] for key in ("all_pass", "families", "questions", "failed_families", "failed_questions", "provider_models")}))


if __name__ == "__main__":
    main()
