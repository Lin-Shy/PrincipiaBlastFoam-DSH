"""构建独立于冻结 v5 的第2章 50 事实族、300 题评测集。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import time

from build_natural_navigation_v2 import api_call, corpus_manifest, response_value, sha, wire, write

MODEL = "deepseek-flash"
STYLE_NUMBERS = (1, 2, 3, 5, 6, 7)
STYLES = (
    "口语化的简短求助", "先说工程目标、再询问资料入口", "先说必须保留或不能误改的约束",
    "有经验工程师的简洁请求", "初次接触该任务的用户求助", "面向团队成员的工程交接说明",
)


def read(path: Path):
    return json.loads(path.read_text())


def credential(path: Path) -> str:
    settings = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip().lower()] = value.strip().strip("\"'")
    if settings.get("model") != MODEL or settings.get("base_url", "").rstrip("/") != "https://api.deepseek.com":
        raise ValueError("llm-setting must select the exact deepseek-flash model and official API")
    key = settings.get("api_key", "")
    if not key or any(char.isspace() for char in key):
        raise ValueError("missing API_KEY in llm-setting")
    return key


def request(payload: dict, key: str, record: Path) -> dict:
    body = {"model": MODEL, "temperature": 0 if payload["task"].startswith("审核") else 0.7,
            "thinking": {"type": "disabled"}, "max_tokens": 2600,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "只返回一个有效 JSON 对象。"},
                         {"role": "user", "content": wire(payload)}]}
    value = response_value(api_call(body, key, record))
    if isinstance(value, dict) and value.get("type") == "json_object" and isinstance(value.get("output"), dict):
        value = value["output"]
    return value


def verified_evidence(spec: dict, corpus: Path, files: dict) -> list[dict]:
    result = []
    kinds = set()
    for index, (path, start, end) in enumerate(spec["evidence"], 1):
        if path not in files or not isinstance(start, int) or not isinstance(end, int):
            raise ValueError(f"unlisted source/range: {spec['id']} {path}")
        raw = (corpus / path).read_bytes()
        lines = raw.decode().splitlines()
        if not 1 <= start <= end <= len(lines):
            raise ValueError(f"invalid range: {spec['id']} {path}:{start}-{end}")
        quote = "\n".join(lines[start - 1:end])
        kind = files[path]["source_kind"]
        kinds.add(kind)
        result.append({"id": f"{spec['id']}:e{index}", "path": path, "start": start, "end": end,
                       "source_kind": kind, "sha256": sha(raw), "quote": quote,
                       "quote_sha256": sha(quote), "pdf_page": None, "status": "verified_original_bytes"})
    expected = {"manual", "tutorial"} if spec["category"] == "cross" else {spec["category"]}
    if kinds != expected:
        raise ValueError(f"category/evidence mismatch for {spec['id']}: {kinds}")
    return result


def check_isolation(specs: list[dict], old: list[dict]) -> None:
    if len(specs) != 20 or len({s["id"] for s in specs}) != 20:
        raise ValueError("fallback requires exactly 20 distinct new families")
    counts = {(c, split): sum(s["category"] == c and s["split"] == split for s in specs)
              for c in ("tutorial", "manual", "cross") for split in ("dev", "holdout")}
    if counts != {("tutorial", "dev"): 6, ("tutorial", "holdout"): 1,
                  ("manual", "dev"): 6, ("manual", "holdout"): 1,
                  ("cross", "dev"): 5, ("cross", "holdout"): 1}:
        raise ValueError(f"unexpected category/split allocation: {counts}")
    ranges = []
    for row in old + specs:
        for ev in row["evidence"]:
            if isinstance(ev, dict):
                path, start, end = ev["path"], ev["start"], ev["end"]
            else:
                path, start, end = ev
            ranges.append((row.get("family", row.get("id")), row["split"], row in specs, path, start, end))
    for i, (family, split, is_new, path, start, end) in enumerate(ranges):
        for other, other_split, other_is_new, other_path, other_start, other_end in ranges[:i]:
            if (is_new or other_is_new) and family != other and split != other_split and path == other_path and start <= other_end and other_start <= end:
                raise ValueError(f"cross-split required evidence overlap: {family}/{other} {path}")


def audit_family(spec: dict, old_summaries: list[dict], key: str, records: Path) -> dict:
    evidence = [{k: e[k] for k in ("path", "start", "end", "quote")}
                for e in spec["verified_evidence"]]
    reviews = []
    for reviewer in (1, 2):
        prompt = {"task": "审核新增事实族是否可纳入检索评测", "reviewer": reviewer,
                  "requirements": ["仅依据提供的原文区间判断 gold 是否完整、准确、唯一。",
                                   "判断新族与旧族是否考查同一必要事实；同案不同独立事实可接受。",
                                   "跨来源族须真正需要手册和教程两边证据。",
                                   "不要参考另一位评审的结论，发现实质重复或证据不足必须拒绝。"],
                  "candidate": {k: spec[k] for k in ("id", "category", "question_intent", "gold")},
                  "evidence": evidence, "old_families": old_summaries,
                  "output": {"pass": "布尔值", "reason": "简短具体说明", "closest_old_family": "若有则填，否则空字符串"}}
        record = records / spec["id"] / f"fact-review-{reviewer}-{sha(wire(prompt))[:12]}.json"
        value = request(prompt, key, record)
        if not isinstance(value, dict) or type(value.get("pass")) is not bool:
            raise ValueError(f"malformed fact review: {spec['id']} reviewer {reviewer}")
        reviews.append(value)
    if not all(r["pass"] for r in reviews):
        raise ValueError(f"fact review rejected {spec['id']}: {reviews}")
    return {"reviewers": reviews, "passed": True}


def generate_family(spec: dict, key: str, records: Path) -> dict:
    accepted = {}
    attempts = []
    evidence = [{k: e[k] for k in ("path", "start", "end", "quote")}
                for e in spec["verified_evidence"]]
    for attempt in range(1, 7):
        prompt = {"task": "为同一证据充分的事实族写六道独立可理解的中文工程资料检索问题",
                  "intent": spec["question_intent"], "gold_for_internal_reference_only": spec["gold"],
                  "original_evidence_for_internal_reference_only": evidence,
                  "styles_in_order": list(STYLES),
                  "rules": ["六题问相同事实，不能增加或删减所需证据。",
                            "每题必须独立可理解；保留案例、模型、材料或功能的自然锚点，禁止无先行对象的这两个、上述、它们。",
                            "可以询问当前值、数量、模式和作用；问题本身不要写出 gold 中的答案值。不给原始路径、行号、代码反引号或评分提示。",
                            "第三种风格中的约束可以是不要混淆来源或对象，不能捏造用户要修改配置。",
                            "18至240个中文字符，表达自然、具体，不能只换一两个词。"],
                  "failed_styles_to_rewrite": [i for i in range(6) if i not in accepted],
                  "output": {"questions": "按风格顺序给恰好六个字符串"}}
        record = records / spec["id"] / f"questions-{attempt}-{sha(wire(prompt))[:12]}.json"
        result = request(prompt, key, record)
        questions = result.get("questions") if isinstance(result, dict) else None
        if not isinstance(questions, list) or len(questions) != 6 or not all(isinstance(q, str) for q in questions):
            attempts.append({"attempt": attempt, "error": "not six strings"})
            continue
        reviewers = []
        for reviewer in (1, 2):
            review_prompt = {"task": "审核六道资料检索问题的语义、唯一性与独立可理解性",
                             "reviewer": reviewer, "independent_review": True,
                             "intent": spec["question_intent"], "gold": spec["gold"], "evidence": evidence,
                             "questions": questions,
                             "requirements": ["每题必须仅依靠公开表述定位唯一对象，不依赖隐藏题族名。",
                                              "六题所需 gold 和必要证据一致；询问答案值是正常问题，只有题干已经断言或给出答案值才算泄露。",
                                              "表达自然并符合指定风格；跨来源题确需两种来源。",
                                              "必须逐题返回六个对象；不能合并为总体评论。不成立时指出具体索引与原因。"],
                             "output_format_example": {"items": [{"index": i, "pass": True, "reason": ""} for i in range(6)]}}
            review_record = records / spec["id"] / f"question-review-{attempt}-{reviewer}-{sha(wire(review_prompt))[:12]}.json"
            value = request(review_prompt, key, review_record)
            items = value.get("items") if isinstance(value, dict) else None
            if not isinstance(items, list) or len(items) != 6:
                raise ValueError(f"malformed question review {spec['id']}: {reviewer}")
            by_index = {int(item["index"]): item for item in items}
            if set(by_index) != set(range(6)):
                raise ValueError(f"malformed question indices {spec['id']}: {reviewer}")
            reviewers.append(by_index)
        issues = {}
        for i, question in enumerate(questions):
            failures = []
            if not 18 <= len(question) <= 240 or "`" in question or "::" in question or re.search(r"\b(?:这两个|上述|它们)\b", question):
                failures.append("deterministic public-question rule")
            for reviewer, items in enumerate(reviewers, 1):
                if items[i].get("pass") is not True:
                    failures.append(f"reviewer{reviewer}:{items[i].get('reason', '')}")
            if failures:
                issues[i] = failures
            elif i not in accepted:
                accepted[i] = {"question": question, "attempt": attempt}
        attempts.append({"attempt": attempt, "issues": issues})
        if len(accepted) == 6:
            return {"questions": [accepted[i]["question"] for i in range(6)],
                    "selected_attempts": [accepted[i]["attempt"] for i in range(6)], "attempts": attempts}
    raise ValueError(f"six reviewed variants not obtained: {spec['id']}, slots {sorted(set(range(6))-set(accepted))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v5", type=Path, required=True)
    parser.add_argument("--specs", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if (args.output / "manifest.json").exists():
        raise FileExistsError("v6 dataset is frozen; do not overwrite")
    args.output.mkdir(parents=True, exist_ok=True)
    key = credential(args.settings)
    old_annotations = read(args.v5 / "dev.annotations.json") + read(args.v5 / "holdout.annotations.json")
    old_questions = read(args.v5 / "dev.questions.json") + read(args.v5 / "holdout.questions.json")
    specs = read(args.specs)
    check_isolation(specs, old_annotations)
    files = corpus_manifest(args.corpus)
    if files != read(args.v5 / "corpus-manifest.json"):
        raise ValueError("authoritative corpus differs from frozen v5 manifest")
    old_summaries = [{"id": a["family"], "category": a["category"], "gold": a["gold"],
                      "evidence": [{"path": e["path"], "start": e["start"], "end": e["end"]} for e in a["evidence"]]}
                     for a in old_annotations]
    for spec in specs:
        spec["verified_evidence"] = verified_evidence(spec, args.corpus, files)
    records = args.output / "review-records"
    built = {}
    failures = []
    def work(spec):
        fact = audit_family(spec, old_summaries, key, records)
        questions = generate_family(spec, key, records)
        return {"fact": fact, "questions": questions}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                built[spec["id"]] = future.result()
                print("PASS", spec["id"], flush=True)
            except Exception as error:
                failures.append({"id": spec["id"], "type": type(error).__name__, "reason": str(error)})
                print("FAIL", spec["id"], type(error).__name__, str(error)[:180], flush=True)
    if failures:
        write(args.output / "build-failures.json", failures)
        raise RuntimeError(f"{len(failures)} facts/questions failed review; dataset not frozen")
    selected = set(STYLE_NUMBERS)
    public = {"dev": [q for q in old_questions if int(q["id"].split("-n")[-1]) in selected and q["split"] == "dev"],
              "holdout": [q for q in old_questions if int(q["id"].split("-n")[-1]) in selected and q["split"] == "holdout"]}
    private = {"dev": [a for a in old_annotations if a["split"] == "dev"],
               "holdout": [a for a in old_annotations if a["split"] == "holdout"]}
    summary = []
    for index, spec in enumerate(specs, 31):
        split = spec["split"]
        annotation = {"split": split, "category": spec["category"], "family": spec["id"], "id": spec["id"],
                      "legacy_id": f"N{index:03d}", "difficulty": "medium", "intents": ["资料检索", "证据核验"],
                      "concepts": [], "cases": [], "targets": [], "gold": spec["gold"], "allowed": [],
                      "forbidden": ["声称已实际运行或修改案例", "把手册默认值当作教程实例值"],
                      "ambiguity": [], "evidence": spec["verified_evidence"],
                      "required_sources": ["manual", "tutorial"] if spec["category"] == "cross" else [spec["category"]],
                      "score_rule": "natural-navigation-quality-v2"}
        private[split].append(annotation)
        for style_number, style, question in zip(STYLE_NUMBERS, STYLES, built[spec["id"]]["questions"]["questions"]):
            public[split].append({"id": f"N{index:03d}-n{style_number}", "family_id": spec["id"],
                                  "item_id": spec["id"], "question": question, "split": split, "style": style})
        summary.append({"id": spec["id"], "fact_review": built[spec["id"]]["fact"],
                        "question_review": built[spec["id"]]["questions"]})
    if tuple(map(len, (private["dev"], private["holdout"], public["dev"], public["holdout"]))) != (35, 15, 210, 90):
        raise ValueError("wrong final family/question counts")
    all_questions = [q["question"].strip() for rows in public.values() for q in rows]
    if len(set(all_questions)) != len(all_questions):
        raise ValueError("duplicate public question across families/splits")
    write(args.output / "corpus-manifest.json", files)
    for split in ("dev", "holdout"):
        write(args.output / f"{split}.questions.json", public[split])
        write(args.output / f"{split}.annotations.json", private[split])
    write(args.output / "review-summary.json", summary)
    write(args.output / "scoring-rules.json", read(args.v5 / "scoring-rules.json"))
    artifacts = {p.relative_to(args.output).as_posix(): sha(p.read_bytes()) for p in sorted(args.output.rglob("*"))
                 if p.is_file() and p.name != "manifest.json"}
    result = {"schema": "natural-navigation-qa-v6", "created_unix_ns": time.time_ns(), "model": MODEL,
              "parent_v5_manifest_sha256": sha((args.v5 / "manifest.json").read_bytes()),
              "candidate_specs_sha256": sha(args.specs.read_bytes()), "families": 50, "variants_per_family": 6,
              "counts": {"dev_families": 35, "dev_questions": 210, "holdout_families": 15, "holdout_questions": 90},
              "split_by_family": {a["family"]: a["split"] for a in old_annotations} | {s["id"]: s["split"] for s in specs},
              "corpus": {"readable_files": len(files), "identity": sha(wire(files))},
              "review": {"new_families": 20, "independent_fact_reviewers": 2, "independent_question_reviewers": 2},
              "artifacts": artifacts}
    write(args.output / "manifest.json", result)
    print(wire({k: result[k] for k in ("families", "counts", "corpus")}))


if __name__ == "__main__":
    main()
