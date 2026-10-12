"""Build the 240-question natural-language Chapter 2 benchmark with Flash.

The compiler migrates only the semantic families and source-grounded grading
contracts from the superseded benchmark.  Public questions are generated and
reviewed with ``deepseek-flash``.  Graph builders and retrieval implementations
must never read the evaluator-only annotations or generation records.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"
SEED = "20260914"
VARIANT_COUNT = 8
DEV_FAMILIES_PER_CATEGORY = 6
STYLES = (
    "口语化的简短求助",
    "先说工程目标、再询问资料入口",
    "先说必须保留或不能误改的约束",
    "先提出问题、再补充目标和约束",
    "有经验工程师的简洁请求",
    "初次接触该任务的用户求助",
    "面向团队成员的工程交接说明",
    "换一种自然语序完整复述同一需求",
)
COMMON_PATH_PARTS = {
    "tutorials", "manual", "markdown", "system", "constant", "validation",
    "fluid", "solid", "readme", "allrun", "allclean", "type", "value",
    "internalfield", "boundaryfield", "functions",
}


def wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(raw: bytes | str) -> str:
    if isinstance(raw, str):
        raw = raw.encode()
    return hashlib.sha256(raw).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def decode_json(content: str):
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    decoder = json.JSONDecoder(strict=False)
    for _ in range(64):
        try:
            value, _ = decoder.raw_decode(candidate)
            break
        except json.JSONDecodeError as error:
            # Flash occasionally serializes an integer as ``5"`` in an
            # otherwise valid JSON object.  Remove only that impossible quote.
            if (
                error.pos > 0 and candidate[error.pos] == '"'
                and candidate[error.pos - 1].isdigit()
                and error.pos + 1 < len(candidate)
                and candidate[error.pos + 1] in {',', '}'}
            ):
                candidate = candidate[:error.pos] + candidate[error.pos + 1:]
                continue
            quote = error.pos - 1
            repairable = (
                error.msg.startswith("Expecting ',' delimiter")
                and quote >= 0 and candidate[quote] == '"'
                and error.pos < len(candidate)
                and candidate[error.pos] not in {'"', ',', '}', ']'}
            )
            if not repairable:
                raise
            candidate = candidate[:quote] + '\\"' + candidate[quote + 1:]
    else:
        raise ValueError("too many malformed quote repairs in Flash JSON")
    if isinstance(value, dict) and set(value) == {"type", "content"} and value["type"] == "json_object":
        inner = value["content"]
        return decode_json(inner) if isinstance(inner, str) else inner
    return value


def api_call(body: dict, key: str, record: Path) -> dict:
    identity = sha(wire(body))
    events = []
    if record.exists():
        saved = read(record)
        if saved.get("request_sha256") != identity:
            raise ValueError(f"request changed for resumable record: {record}")
        events = list(saved.get("events", []))
        if saved.get("status") == "response":
            payload = saved["response"]
            if payload.get("model") != MODEL:
                raise ValueError(f"provider model mismatch in {record}")
            return payload
    for attempt in range(3):
        started = time.monotonic()
        try:
            request = Request(
                ENDPOINT,
                data=wire(body).encode(),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            )
            with urlopen(request, timeout=180) as response:
                payload = json.loads(response.read().decode())
            events.append({"status": "response", "seconds": time.monotonic() - started})
            saved = {
                "status": "response", "request": body, "request_sha256": identity,
                "response": payload, "events": events,
            }
            write(record, saved)
            if payload.get("model") != MODEL:
                raise ValueError(f"provider returned {payload.get('model')!r}, expected {MODEL!r}")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            detail = None
            if isinstance(error, HTTPError):
                detail = error.read().decode(errors="replace")[:1000]
            events.append({
                "status": "transport_error", "attempt": attempt + 1,
                "error_type": type(error).__name__, "http_status": getattr(error, "code", None),
                "seconds": time.monotonic() - started, "usage": None, "provider_detail": detail,
            })
            write(record, {
                "status": "transport_error", "request": body,
                "request_sha256": identity, "events": events,
            })
            if getattr(error, "code", None) in {401, 402, 403}:
                break
            time.sleep(1 + attempt)
    raise RuntimeError(f"Flash transport failed; resumable record: {record}")


def response_value(payload: dict):
    content = payload["choices"][0]["message"]["content"]
    return decode_json(content)


def corpus_manifest(corpus: Path) -> dict:
    rows = {}
    for prefix in (Path("manual/markdown"), Path("tutorials")):
        root = corpus / prefix
        if not root.is_dir():
            raise ValueError(f"missing authoritative corpus subtree: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "\0" in text:
                continue
            relative = path.relative_to(corpus).as_posix()
            rows[relative] = {
                "sha256": sha(raw), "bytes": len(raw), "characters": len(text),
                "source_kind": "manual" if relative.startswith("manual/") else "tutorial",
            }
    return rows


def verify_annotation(annotation: dict, corpus: Path, manifest: dict) -> None:
    for evidence in annotation["evidence"]:
        path = evidence["path"]
        if path not in manifest:
            raise ValueError(f"evidence outside authoritative text corpus: {path}")
        raw = (corpus / path).read_bytes()
        if sha(raw) != evidence["sha256"]:
            raise ValueError(f"evidence source drift: {path}")
        lines = raw.decode().splitlines()
        quote = "\n".join(lines[evidence["start"] - 1:evidence["end"]])
        if quote != evidence["quote"] or sha(quote) != evidence["quote_sha256"]:
            raise ValueError(f"evidence range drift: {evidence['id']}")


def split_families(annotations: list[dict]) -> dict[str, str]:
    by_category: dict[str, list[dict]] = {}
    for annotation in annotations:
        by_category.setdefault(annotation["category"], []).append(annotation)
    if sorted(map(len, by_category.values())) != [10, 10, 10]:
        raise ValueError("expected ten families in each of tutorial/manual/cross")
    result = {}
    for category, rows in sorted(by_category.items()):
        ordered = sorted(rows, key=lambda row: sha(f"{SEED}:{category}:{row['family']}"))
        for index, row in enumerate(ordered):
            result[row["family"]] = "dev" if index < DEV_FAMILIES_PER_CATEGORY else "holdout"
    return result


def sensitive_tokens(annotation: dict) -> set[str]:
    tokens = set()
    for case in annotation.get("cases", []):
        tokens.add(case.casefold())
        parts = case.split("/")
        for part in (parts[0], parts[-1]):
            if len(part) >= 4:
                tokens.add(part.casefold())
    for evidence in annotation["evidence"]:
        basename = Path(evidence["path"]).name
        folded = basename.casefold()
        if len(basename) >= 4 and folded not in COMMON_PATH_PARTS and (
            any(char.isupper() for char in basename)
            or basename.endswith(("Dict", "Properties", ".orig"))
        ):
            tokens.add(folded)
    for target in annotation.get("targets", []):
        for part in re.split(r"[/,:()\s]+", target):
            folded = part.casefold()
            if len(part) >= 3 and folded not in COMMON_PATH_PARTS and (
                (any(char.isupper() for char in part) and any(char.islower() for char in part))
                or "_" in part or part.endswith(("Dict", "Properties"))
                or ("::" in target and not part.isupper())
            ):
                tokens.add(folded)
    return tokens


def deterministic_issues(question: str, annotation: dict) -> list[str]:
    issues = []
    folded = question.casefold()
    leaked = sorted(token for token in sensitive_tokens(annotation) if token in folded)
    if leaked:
        issues.append("technical_identifier_leak:" + ",".join(leaked))
    if "/" in question or "`" in question or "::" in question:
        issues.append("path_or_code_syntax")
    if re.search(r"\b[A-Za-z][A-Za-z0-9_]*(?:Foam|Dict|Properties)\b", question):
        issues.append("solver_file_or_dictionary_name")
    if len(question) < 18 or len(question) > 240:
        issues.append("length_out_of_range")
    return issues


def generator_body(annotation: dict, source_questions: list[str], retry_feedback: object | None) -> dict:
    private_contract = {
        key: annotation.get(key)
        for key in ("intents", "concepts", "targets", "gold", "allowed", "forbidden", "ambiguity")
    }
    prompt = {
        "task": "为同一个blastFoam资料检索事实家族撰写8条中文自然用户需求。",
        "rules": [
            "八条问题必须语义等价并要求相同gold；只能改变说话方式，不能增加或删减评分要求。",
            "保留旧问题中用户主动给出的目标、数值、操作和保留约束，但不要透露资料里的当前答案值。",
            "用户不知道准确案例名、求解器名、文件/目录名、字典名、配置键、证据行或标准答案术语。",
            "不得使用路径、代码反引号、内部题号、gold、评分、证据等元话语。",
            "可以自然地要求查找参考、比较设置、说明应改哪里和哪些内容不能直接照搬。",
            "每条18至240个中文字符；自然、具体、像真实工程人员提问。",
        ],
        "styles_in_order": list(STYLES),
        "old_questions_for_semantic_intent_only": source_questions,
        "private_grading_contract_do_not_quote": private_contract,
        "output": {"questions": ["恰好8个字符串，顺序对应styles_in_order"]},
        "retry_feedback": retry_feedback,
    }
    return {
        "model": MODEL, "temperature": 0.7, "thinking": {"type": "disabled"},
        "max_tokens": 2500, "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return one valid JSON object only."},
            {"role": "user", "content": wire(prompt)},
        ],
    }


def reviewer_body(annotation: dict, source_questions: list[str], questions: list[str], reviewer: int) -> dict:
    prompt = {
        "task": "只审核8个自然语言问题与旧问题的用户意图是否语义等价、表达是否自然。",
        "reviewer": reviewer,
        "independence_instruction": "独立判断，不假设另一位评审会纠错。",
        "requirements": [
            "以old_questions中的用户请求为唯一语义基准，保留其中的目标值、比较对象和保留/不修改约束。",
            "每条都必须能用同一组gold评分，不得引入需要新gold的新场景条件。",
            "问题询问当前值、默认值、文件或设置位置，是正常用户意图，不是答案泄漏。",
            "允许用通用物理场景、材料名和功能描述替换旧问题中的仓库专名。",
            "private_annotation中的forbidden是回答评分约束；old_questions没有要求用户明说的禁止项，不得反过来要求新问题复述。",
            "表达应自然，不是把配置键机械替换成同义词。",
            "不要检查或声称问题含有具体标识符、路径、键名或答案值；这些由确定性程序逐字检查。",
            "pass为true时issues必须为空；pass为false时只写一个不超过30字的语义缺失或新增点。",
        ],
        "old_questions": source_questions,
        "private_annotation": {
            key: annotation.get(key)
            for key in ("intents", "concepts", "cases", "targets", "gold", "allowed", "forbidden", "ambiguity")
        },
        "questions": questions,
        "output": {
            "items": [{"index": "0到7", "pass": "布尔值", "issues": ["仅语义缺失或新增；通过则空数组"]}],
            "all_pass": "仅当8条全部通过时为true",
        },
    }
    return {
        "model": MODEL, "temperature": 0, "thinking": {"type": "disabled"},
        "max_tokens": 3000, "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return one valid JSON object only."},
            {"role": "user", "content": wire(prompt)},
        ],
    }


def validate_review(value: object) -> list[dict]:
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError("review response lacks items")
    items = value["items"]
    if len(items) != VARIANT_COUNT:
        raise ValueError("review response must contain eight items")
    normalized = sorted(items, key=lambda item: int(item["index"]))
    if [int(item["index"]) for item in normalized] != list(range(VARIANT_COUNT)):
        raise ValueError("review indices differ from 0..7")
    return normalized


def build_family(annotation: dict, old_questions: list[str], key: str, records: Path) -> dict:
    family_dir = records / annotation["id"]
    feedback = None
    accepted: dict[int, dict] = {}
    attempt_reviews = []
    for generation_attempt in range(1, 7):
        body = generator_body(annotation, old_questions, feedback)
        generation_name = f"generation-v3-{generation_attempt}-{sha(wire(body))[:12]}.json"
        payload = api_call(body, key, family_dir / generation_name)
        value = response_value(payload)
        questions = value.get("questions") if isinstance(value, dict) else None
        if not isinstance(questions, list) or len(questions) != VARIANT_COUNT or not all(isinstance(q, str) for q in questions):
            feedback = {"error": "必须返回恰好8个字符串"}
            continue
        deterministic = [deterministic_issues(question, annotation) for question in questions]
        reviews = []
        for reviewer in (1, 2):
            review_body = reviewer_body(annotation, old_questions, questions, reviewer)
            review_name = f"generation-v3-{generation_attempt}-review-{reviewer}-{sha(wire(review_body))[:12]}.json"
            review_payload = api_call(
                review_body, key,
                family_dir / review_name,
            )
            reviews.append(validate_review(response_value(review_payload)))
        failed = []
        for index in range(VARIANT_COUNT):
            issues = list(deterministic[index])
            for reviewer, review in enumerate(reviews, 1):
                if review[index].get("pass") is not True:
                    issues.extend(f"reviewer{reviewer}:{issue}" for issue in review[index].get("issues", []))
            if issues:
                failed.append({"index": index, "issues": issues})
            elif index not in accepted:
                accepted[index] = {"question": questions[index], "attempt": generation_attempt}
        attempt_reviews.append({"attempt": generation_attempt, "reviews": reviews, "failed": failed})
        if len(accepted) == VARIANT_COUNT:
            selected = [accepted[index] for index in range(VARIANT_COUNT)]
            return {
                "questions": [item["question"] for item in selected],
                "generation_attempt": generation_attempt,
                "selected_attempts": [item["attempt"] for item in selected],
                "reviews": attempt_reviews,
            }
        missing = [index for index in range(VARIANT_COUNT) if index not in accepted]
        feedback = {
            "missing_style_indices": missing,
            "rejected_items": [item for item in failed if item["index"] in missing],
            "instruction": "仍返回完整8条；重点重写尚未获得双审通过的风格槽，保持同一语义契约。",
        }
    raise RuntimeError(
        f"family lacks accepted style slots after six attempts: {annotation['id']} "
        f"missing={sorted(set(range(VARIANT_COUNT)) - set(accepted))}"
    )


def compile_dataset(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    if output.exists() and (output / "manifest.json").exists():
        raise FileExistsError(f"frozen output already exists: {output}")
    output.mkdir(parents=True, exist_ok=True)
    dev_annotations = read(args.dev_annotations)
    holdout_annotations = read(args.holdout_annotations)
    annotations = dev_annotations + holdout_annotations
    if len(annotations) != 30 or len({row["family"] for row in annotations}) != 30:
        raise ValueError("expected 30 unique source fact families")
    old_questions = read(args.dev_questions) + read(args.holdout_questions)
    questions_by_item: dict[str, list[str]] = {}
    for row in old_questions:
        questions_by_item.setdefault(row["item_id"], []).append(row["question"])
    corpus = args.corpus.resolve()
    manifest = corpus_manifest(corpus)
    if len(manifest) != 702:
        raise ValueError(f"expected 702 readable corpus files, found {len(manifest)}")
    for annotation in annotations:
        verify_annotation(annotation, corpus, manifest)
    splits = split_families(annotations)
    key = args.key_file.read_text().strip()
    if not key or any(character.isspace() for character in key):
        raise ValueError("key file must contain exactly one credential")

    built = {}
    records = output / "generation-records"
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {
            pool.submit(build_family, annotation, questions_by_item[annotation["id"]], key, records): annotation
            for annotation in annotations
        }
        for future in as_completed(pending):
            annotation = pending[future]
            try:
                built[annotation["id"]] = future.result()
                print(f"PASS {annotation['id']} {annotation['family']}", flush=True)
            except Exception as error:
                failures.append({"id": annotation["id"], "error": type(error).__name__, "reason": str(error)})
                print(f"FAIL {annotation['id']} {type(error).__name__}: {error}", flush=True)
    if failures:
        write(output / "generation-failures.json", failures)
        raise RuntimeError(f"{len(failures)} families failed generation/review; see generation-failures.json")

    public = {"dev": [], "holdout": []}
    private = {"dev": [], "holdout": []}
    generation_summary = []
    for annotation in sorted(annotations, key=lambda row: row["id"]):
        split = splits[annotation["family"]]
        migrated = dict(annotation)
        migrated["legacy_id"] = migrated.pop("id")
        migrated["id"] = annotation["family"]
        migrated["split"] = split
        migrated["score_rule"] = "natural-navigation-quality-v2"
        private[split].append(migrated)
        family_result = built[annotation["id"]]
        for index, question in enumerate(family_result["questions"], 1):
            public[split].append({
                "id": f"{annotation['id']}-n{index}", "item_id": annotation["family"],
                "family_id": annotation["family"],
                "question": question, "split": split, "style": STYLES[index - 1],
            })
        generation_summary.append({
            "legacy_id": annotation["id"], "family_id": annotation["family"], "split": split,
            "generation_attempt": family_result["generation_attempt"], "model": MODEL,
            "selected_attempts": family_result["selected_attempts"],
            "reviewers": 2, "all_pass": True,
        })

    if len(public["dev"]) != 144 or len(public["holdout"]) != 96:
        raise ValueError("unexpected split question counts")
    write(output / "corpus-manifest.json", manifest)
    write(output / "dev.questions.json", public["dev"])
    write(output / "dev.annotations.json", private["dev"])
    write(output / "holdout.questions.json", public["holdout"])
    write(output / "holdout.annotations.json", private["holdout"])
    write(output / "scoring-rules.json", {
        "schema": "natural-navigation-scoring-v2",
        "primary": "strict_success",
        "strict_success": "all applicable gold points correct and supported; no forbidden conclusion",
        "secondary": ["answer_correctness", "citation_precision", "required_evidence_recall", "source_scope_completeness"],
        "independent_unit": "family_id",
        "statistics": "paired family bootstrap; variants and replicates remain clustered within family",
        "acceptance": {
            "strict_success_point_improvement_pp": 8.0,
            "comparators": ["no_graph", "max(graphify_native, graphify_text_adapter)"],
            "paired_family_bootstrap_95ci_lower_bound": ">0",
            "citation_precision": "not below strongest comparator",
        },
    })
    write(output / "generation-summary.json", generation_summary)
    artifacts = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.relative_to(output).as_posix()] = sha(path.read_bytes())
    model_records = list(records.rglob("*.json"))
    provider_models = sorted({read(path)["response"].get("model") for path in model_records if read(path).get("status") == "response"})
    result = {
        "schema": "natural-navigation-qa-v2", "created_unix_ns": time.time_ns(),
        "seed": SEED, "model": MODEL, "provider_models": provider_models,
        "families": 30, "variants_per_family": VARIANT_COUNT,
        "counts": {"dev_families": 18, "dev_questions": 144, "holdout_families": 12, "holdout_questions": 96},
        "split_by_family": dict(sorted(splits.items())),
        "corpus": {"readable_files": len(manifest), "identity": sha(wire(manifest))},
        "generation": {"successful_api_records": len(model_records), "double_reviewed": True, "deterministic_leak_scan": True},
        "source_benchmark_retained": False,
        "artifacts": artifacts,
    }
    if provider_models != [MODEL]:
        raise ValueError(f"non-Flash generation record: {provider_models}")
    write(output / "manifest.json", result)
    print(wire({key: result[key] for key in ("model", "families", "counts", "corpus", "generation")}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-questions", type=Path, required=True)
    parser.add_argument("--dev-annotations", type=Path, required=True)
    parser.add_argument("--holdout-questions", type=Path, required=True)
    parser.add_argument("--holdout-annotations", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    compile_dataset(args)


if __name__ == "__main__":
    main()
