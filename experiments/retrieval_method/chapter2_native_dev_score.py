"""独立开发gold评分：核验实际送达原文，不向检索器提供标注。"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

from canonical_evidence_v1 import score, validate_gold, _overlap, _contains
from chapter2_canonical_delivery import render


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_metrics(gold, units):
    result = score(gold, units, budgets=())
    # 旧公式以gold原子数限定理想单元数，可能nDCG>1。保留旧值审计，
    # 新值仅相对已观测候选池的分级理想排序，不能当穷尽语料相关性。
    atoms = validate_gold(gold)
    grades = [2 if any(_contains(u,a) for a in atoms) else 1 if any(_overlap(u,a) for a in atoms) else 0 for u in units]
    for key, metrics in result["top_k"].items():
        k = int(key)
        dcg = sum((2**grade-1)/math.log2(i+2) for i,grade in enumerate(grades[:k]))
        idcg = sum((2**grade-1)/math.log2(i+2) for i,grade in enumerate(sorted(grades,reverse=True)[:k]))
        metrics["legacy_ndcg_atom_count_denominator"] = metrics.pop("ndcg")
        metrics["ndcg_observed_candidate_pool"] = dcg/idcg if idcg else 0.0
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("probe", "annotations", "corpus", "output"):
        p.add_argument("--"+name,type=Path,required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("new isolated scoring artifact required")
    annotations = json.loads(args.annotations.read_text())
    if any(a["split"]!="dev" for a in annotations):
        raise ValueError("development gold only")
    gold = {a["id"]:a for a in annotations}
    protocol_file = args.probe/"protocol.json"
    protocol = json.loads(protocol_file.read_text())
    if not (args.probe/"completion.json").exists():
        raise ValueError("finish complete development grid before scoring")
    sources, rows, checked = {}, [], 0
    for q in protocol["questions"]:
        annotation = gold[q["family_id"]]
        for arm in protocol["arms"]:
            file = args.probe/"responses"/q["id"]/(arm+".json")
            packet = json.loads(file.read_text())
            if packet["question"]!=q or packet["protocol_sha256"]!=sha(protocol_file):
                raise ValueError("response input drift")
            for unit in packet["canonical_units"]:
                if unit.get("mapping_status") == "unmappable":
                    continue
                path = unit["path"]
                if path not in sources:
                    raw = (args.corpus/path).read_bytes()
                    sources[path] = (hashlib.sha256(raw).hexdigest(),raw.decode().splitlines())
                source_hash, lines = sources[path]
                if unit["source_sha256"]!=source_hash or lines[unit["start"]-1:unit["end"]]!=unit["lines"]:
                    raise ValueError("canonical source drift")
                checked += len(unit["lines"])
            for atom in annotation["evidence"]:
                if sha(args.corpus/atom["path"])!=atom["sha256"]:
                    raise ValueError("gold source drift")
            native = packet["native"]
            if arm=="no_cross" and any(step["cross_source"] for item in native["items"] for step in item["route"]):
                raise ValueError("no-cross leaked cross traversal")
            if arm=="node_scan" and any(item["route"] for item in native["items"]):
                raise ValueError("node scan traversed graph")
            unbounded = render(packet["canonical_units"])
            metrics = rank_metrics(annotation["evidence"],unbounded["units"])
            budgets = {}
            for budget in protocol["budgets"]:
                delivery = packet["deliveries"][str(budget)]
                if delivery!=render(packet["canonical_units"],budget):
                    raise ValueError("actual delivery content/character drift")
                m = score(annotation["evidence"],delivery["units"],budgets=(budget,))["by_returned_character_budget"][str(budget)]
                budgets[str(budget)]={**m,"actual_returned_characters":len(delivery["text"])}
            rows.append({"id":q["id"],"family_id":q["family_id"],"category":annotation["category"],"arm":arm,
                         "response_sha256":sha(file),"query_seconds":packet["query_seconds"],
                         "rank_metrics":metrics,"by_budget":budgets})
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["category"],row["arm"]].append(row)
    summaries=[]
    for (category,arm), group in sorted(grouped.items()):
        families=defaultdict(list)
        for row in group:
            families[row["family_id"]].append(row)
        budgets={}
        for b in protocol["budgets"]:
            key=str(b)
            budgets[key]={"complete_questions":sum(r["by_budget"][key]["complete_evidence_set_success"] for r in group),
                         "question_complete_rate":statistics.mean(r["by_budget"][key]["complete_evidence_set_success"] for r in group),
                         "family_macro_complete_rate":statistics.mean(statistics.mean(r["by_budget"][key]["complete_evidence_set_success"] for r in rs) for rs in families.values()),
                         "family_macro_atom_recall":statistics.mean(statistics.mean(r["by_budget"][key]["recall"] for r in rs) for rs in families.values()),
                         "mean_returned_characters":statistics.mean(r["by_budget"][key]["actual_returned_characters"] for r in group)}
        summaries.append({"category":category,"arm":arm,"questions":len(group),"families":len(families),
                          "mean_query_seconds":statistics.mean(r["query_seconds"] for r in group),"by_budget":budgets})
    out={"schema":"isolated-development-native-and-actual-delivery-score-v1", "major_round":protocol["major_round"],
         "protocol_sha256":sha(protocol_file),"annotations_sha256":sha(args.annotations),
         "implementation_sha256":sha(Path(__file__)),"model_calls":0,"completed_queries":len(rows),
         "authoritative_lines_checked":checked,"source_files_checked":len(sources),"summary":summaries,"rows":rows,
         "query_policy":protocol["query_policy"],
         "limits":"开发、无答案评分、无正式CI；是否含共享8B规划见query_policy；nDCG仅候选池重排诊断且保留旧分母值；不修改冻结历史。"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:out[k] for k in ("completed_queries","authoritative_lines_checked","source_files_checked","summary")},ensure_ascii=False))


if __name__=="__main__":
    main()
