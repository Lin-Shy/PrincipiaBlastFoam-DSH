"""冻结数据作者审计后的题集；开发包与测试gold物理分目录。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        raise FileExistsError("immutable dataset artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("drafts", "fact-review", "author-audit", "exposure", "corpus", "output", "runtime", "graph"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("new frozen dataset directory required")
    drafts = json.loads(args.drafts.read_text())
    fact_review = json.loads(args.fact_review.read_text())
    author = json.loads(args.author_audit.read_text())
    exposure = json.loads(args.exposure.read_text())
    draft_hash = sha(args.drafts)
    review_protocol = json.loads((args.fact_review.parent / "review_003/protocol.json").read_text())
    if any(item["drafts_sha256"] != draft_hash for item in (author, exposure, review_protocol)):
        raise ValueError("data audit inputs are not the same version")
    if fact_review["completed_calls"] != 46 or fact_review["accepted"] != 46 or fact_review["identity_errors"]:
        raise ValueError("fact/question review gate failed")
    if fact_review["model"] != "qwen3-8b" or fact_review["protocol_sha256"] != sha(args.fact_review.parent / "review_003/protocol.json"):
        raise ValueError("review identity or protocol drift")
    reviewed = {r["id"]: r for r in fact_review["rows"]}
    eligibility = {r["id"]: r for r in author["rows"]}
    families = [f for f in drafts["families"] if eligibility[f["id"]]["decision"] == "author_assessed_new_combination"]
    if len(families) != author["retained_families"] or len(families) != 44:
        raise ValueError("author-reviewed pool changed; revise protocol before freezing")
    if len({f["definition_cluster"] for f in families}) != len(families):
        raise ValueError("same definition cluster appears in multiple fact families")
    for f in families:
        if reviewed[f["id"]]["candidate_accepted"] is not True or len(f["questions"]) != 3 or len(set(f["questions"])) != 3:
            raise ValueError("fact/question review or variants invalid")
        for atom in f["evidence"]:
            file = args.corpus / atom["path"]
            if sha(file) != atom["sha256"] or "\n".join(file.read_text().splitlines()[atom["start"]-1:atom["end"]]) != atom["quote"]:
                raise ValueError("necessary evidence drift")
    seed = "chapter2-aliyun8b-data-v1-20261003"

    def ordered(rows):
        return sorted(rows, key=lambda f: hashlib.sha256((seed + ":" + f["id"]).encode()).hexdigest())

    cross = [f for f in families if f["category"] == "cross"]
    parameters = [f for f in cross if "actual_parameter_definition_units" in f["task_types"]]
    multifile = [f for f in cross if "multiple_tutorial_files_and_concept" in f["task_types"]]
    others = [f for f in cross if f not in parameters and f not in multifile]
    dev_ids = {f["id"] for f in ordered(parameters)[:3] + ordered(multifile)[:2] + ordered(others)[:5]}
    for category in ("manual", "tutorial"):
        dev_ids.add(ordered([f for f in families if f["category"] == category])[0]["id"])
    if len(dev_ids) != 12:
        raise ValueError("stratified split invalid")
    questions, annotations, split_map, task_counts = {"dev": [], "test": []}, {"dev": [], "test": []}, {}, {}
    id_map = {f["id"]: f"F{i+1:03d}" for i, f in enumerate(drafts["families"])}
    source_manifest = {}
    for file in sorted(args.corpus.rglob("*")):
        if file.is_file():
            source_manifest[file.relative_to(args.corpus).as_posix()] = sha(file)
    for f in families:
        identity = id_map[f["id"]]
        split = "dev" if f["id"] in dev_ids else "test"
        evidence = []
        for i, atom in enumerate(f["evidence"], 1):
            evidence.append({**atom, "id": identity + f":e{i}", "quote_sha256": hashlib.sha256(atom["quote"].encode()).hexdigest(),
                             "status": "verified_original_bytes", "pdf_page": None})
        points = []
        if f["category"] == "cross":
            points.append(f"教程{f['case']}的{f['field']}实际选择{f['value']}；保留该字典对象和模型角色，只报告静态声明。")
            points.append("手册对应模型的首段用途/条件为：" + f["allowed_answer_basis"]["manual_definition"])
            for parameter in f.get("parameter_facts", []):
                points.append(f"{f['case']}的{parameter['field']}实例值是{parameter['value']}，不能迁用其他组分或手册默认。")
            for atom in f["evidence"]:
                if atom["source_kind"] == "manual" and atom["id"] != f["id"] + ":manual":
                    points.append("所问公式/变量/单位/默认的原文依据（评价语义与细节，无需照抄排版）：" + atom["quote"])
            if "launch_command" in f["allowed_answer_basis"]:
                points.append("Allrun原始运行命令为" + f["allowed_answer_basis"]["launch_command"] + "；与application声明分开，保留动态写法，不假定执行成功或解析外部RunFunctions。")
        else:
            points = ["回答所问的用途、首式及其明确变量，或教程所指配置值；必要原文依据（无需照抄排版）：" + atom["quote"] for atom in f["evidence"]]
        points.extend(f["ambiguities"])
        annotation = {"split": split, "category": f["category"], "family": identity, "id": identity,
                      "difficulty": "source-grounded", "intents": ["资料检索", "证据核验"],
                      "concepts": [f["value"], f["role"]], "cases": [f["case"]] if f["case"] else [], "targets": [f["field"]],
                      "gold": points, "allowed": ["区分静态配置、手册说明及原文歧义；无需证明运行条件或求解成功"],
                      "forbidden": ["声称已经运行或验证案例", "把手册默认当实例显式配置", "凭同名混淆模型角色或字典组分", "猜测原文未明确的单位或条件"],
                      "ambiguity": f["ambiguities"], "evidence": evidence,
                      "required_sources": sorted({e["source_kind"] for e in evidence}), "task_types": f["task_types"],
                      "score_rule": "aliyun8b-cross-source-quality-v1"}
        annotations[split].append(annotation)
        for i, question in enumerate(f["questions"], 1):
            questions[split].append({"id": identity + f"-n{i}", "family_id": identity, "item_id": identity,
                                     "question": question, "split": split, "style": f"independently-readable-variant-{i}"})
        split_map[identity] = {"draft_id": f["id"], "split": split, "category": f["category"], "definition_cluster": f["definition_cluster"],
                               "rationale": eligibility[f["id"]]["rationale"]}
    for split in questions:
        task_counts[split] = dict(Counter(task for a in annotations[split] for task in a["task_types"]))
    rules = {"schema": "aliyun8b-cross-source-quality-v1", "primary_retrieval": "cross-only complete necessary evidence set at actual delivered-character budget",
             "primary_answer": "all requested gold details correct, complete and supported by answer's own citations; no forbidden conclusion",
             "gold_is_exhaustive_relevance": False, "independent_unit": "fact family; three variants and repeats aggregate inside family",
             "model": "qwen3-8b", "invalid_judge_structure": "separate audit status; never a positive score or substitute gold for omitted answer",
             "statistics": "paired family bootstrap 10000 resamples, seed 20261003; question and family means both reported",
             "human_review": "real blinded sampling protocol must freeze with formal run before test calls; data author is not a human blind reviewer",
             "selection": "at most 3 major development rounds on development package only; no new test calls before implementation/formal protocol freeze"}
    args.output.mkdir(parents=True)
    save(args.output / "development/dev.questions.json", questions["dev"])
    save(args.output / "development/dev.annotations.json", annotations["dev"])
    save(args.output / "development/scoring-rules.json", rules)
    save(args.output / "development/manifest.json", {"schema": "development-only-dataset-manifest-v1", "families": 12, "questions": 36,
         "artifacts": {name: sha(args.output / "development" / name) for name in ("dev.questions.json", "dev.annotations.json", "scoring-rules.json")}})
    save(args.output / "public_test/questions.json", questions["test"])
    save(args.output / "evaluation_only/test.annotations.json", annotations["test"])
    save(args.output / "evaluation_only/scoring-rules.json", rules)
    save(args.output / "evaluation_only/author-split-map.json", split_map)
    save(args.output / "corpus-manifest.json", {"schema": "authoritative-corpus-hashes-v1", "files": source_manifest})
    exposed = {r["id"]: r for r in exposure["rows"]}
    save(args.output / "evaluation_only/exposure-summary.json", {"parent_exposure_sha256": sha(args.exposure),
         "retained_families": len(families), "complete_in_one_historical_session": sum(exposed[f["id"]]["complete_set_in_one_session"] > 0 for f in families),
         "complete_in_historical_union": sum(exposed[f["id"]]["complete_set_in_historical_union"] for f in families),
         "rows": [{"family": id_map[f["id"]], "split": "dev" if f["id"] in dev_ids else "test", "exposure": exposed[f["id"]]} for f in families],
         "limits": exposure["limits"]})
    baseline_files = ("candidate_qa.py", "index_free_graph_evidence.py", "candidate_graph_utils.py", "candidate_paths.py", "candidate_hybrid.py")
    save(args.output / "pre-development-source-state.json", {"graph_sha256": sha(args.graph), "runtime_sha256": {n: sha(args.runtime / n) for n in baseline_files},
          "limits": "数据冻结时生产图/检索实现状态；后续最多3轮开发另立版本，不是正式实现冻结。"})
    save(args.output / "isolation.json", {"test_gold_directory": "evaluation_only", "test_public_questions": "public_test/questions.json",
          "development_runner_dataset_argument": "development", "development_manifest_only_reads_development_files": True,
          "production_inputs": ["graph", "authoritative raw corpus", "public question"],
          "forbidden_production_reads": ["evaluation_only", "data_design", "annotations", "gold", "source-bound author audit"],
          "runtime_read_guard": "must implement and verify during D/E; directory separation alone is not access enforcement",
          "no_test_retrieval_or_tuning": True})
    save(args.output / "manifest.json", {"schema": "aliyun8b-new-combinations-frozen-dataset-v1", "frozen": True,
          "families": 44, "questions": 132, "development": {"families": 12, "cross": 10, "single": 2, "questions": 36},
          "test": {"families": 32, "cross": 27, "single": 5, "questions": 96}, "split_seed": seed,
          "split_policy": "SHA256 deterministic strata: dev 3 parameter cross +2 multi-file cross +5 other cross +1 manual +1 tutorial",
          "selection_basis": "public corpus and data author audit before method development; no retrieval test performance used",
          "input_sha256": {"drafts": draft_hash, "fact_review_accounting": sha(args.fact_review), "semantic_author_audit": sha(args.author_audit), "historical_exposure": sha(args.exposure)},
          "implementation_sha256": sha(Path(__file__)), "task_counts": task_counts,
          "artifacts": {file.relative_to(args.output).as_posix(): sha(file) for file in sorted(args.output.rglob("*")) if file.is_file()},
          "limits": "新事实组合、共享旧语料与部分旧答案组件；作者语义审计不是人工盲审。8B近重复分类曾严重失误，不能作为独立性证明；正式实验披露该局限。测试分离已落盘，读取防护及正式协议仍待D/E。"})
    print(json.dumps({"frozen": True, "families": len(families), "development": len(annotations["dev"]), "test": len(annotations["test"]),
                      "manifest_sha256": sha(args.output / "manifest.json")}))


if __name__ == "__main__":
    main()
