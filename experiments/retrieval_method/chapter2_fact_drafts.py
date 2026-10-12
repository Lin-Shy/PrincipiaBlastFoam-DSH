"""根据已核对公开语料角色创建数据设计草案；不供检索器导入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re


# 公开手册的模型角色，专用于数据设计审查，绝不进入图或检索实现。
ROLE_SELECTION = {
    "04_granular_models.md": {39: "radialModel", 71: "radialModel", 224: "conductivityModel",
                              237: "granularPressureModel", 253: "granularPressureModel",
                              266: "frictionalStressModel", 389: "packingLimitModel"},
    "05_fluid_solid_thermo.md": {100: "thermo", 116: "thermo", 240: "equationOfState",
                                304: "equationOfState", 520: "equationOfState", 679: "equationOfState",
                                716: "equationOfState", 777: "equationOfState", 817: "equationOfState",
                                908: "transport", 1182: "activationModel", 1208: "activationModel"},
    "07_burst_patches.md": {37: "burstModel"},
    "09_diameter_models.md": {5: "diameterModel"},
    "10_flux_evaluation.md": {157: "fluxScheme", 326: "fluxScheme", 387: "div(",
                              430: "timeIntegrator", 493: "timeIntegrator", 615: "timeIntegrator"},
    "11_amr.md": {77: "errorEstimator"},
    "15_function_objects.md": {74: "surfaceFormat"},
    "16_utilities.md": {5: "application", 225: "application"},
    "19_solvers.md": {5: "application", 9: "application", 15: "application", 21: "application",
                      25: "application", 33: "application", 37: "application"},
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("draft is versioned")
    inventory = json.loads(args.inventory.read_text())
    rows, decisions = [], []
    for cluster, group in inventory["cross_candidates"].items():
        definition = group["definition"]
        expected = ROLE_SELECTION.get(Path(definition["path"]).name, {}).get(definition["start"])
        candidates = [n for n in group["instances"] if expected and
                      (n["key"] == expected or expected == "div(" and n["key"].startswith("div("))]
        if group["status"] == "exposed_definition" or not candidates:
            decisions.append({"cluster": cluster, "status": "excluded", "reason": "historical_definition_overlap" if
                              group["status"] == "exposed_definition" else "unsupported_or_mismatched_role_or_alias",
                              "keys": sorted({n["key"] for n in group["instances"]})})
            continue
        candidates.sort(key=lambda n: (bool(n["historical_instance_overlap"]), n["scope"]["case_directory"], n["dictionary"], n["node_id"]))
        node = candidates[0]
        source = args.corpus / definition["path"]
        lines = source.read_text().splitlines()
        # 只取节标题后首个说明段；不把整章、公式或未提问字段机械加入必要gold。
        start = definition["start"] + 1
        while start <= definition["end"] and not lines[start - 1].strip():
            start += 1
        end = start
        while end < definition["end"] and lines[end].strip():
            end += 1
        explanation = "\n".join(lines[start - 1:end])
        if not explanation or explanation.startswith(("```", "|", "$", "#")):
            decisions.append({"cluster": cluster, "status": "excluded", "reason": "no_plain_definition_paragraph"})
            continue
        family = f"draft-cross-{len(rows)+1:03d}"
        atom = {"id": family + ":manual", "path": definition["path"], "start": definition["start"], "end": end,
                "sha256": sha(source), "quote": "\n".join(lines[definition["start"]-1:end]), "source_kind": "manual"}
        instance_atoms = []
        for i, evidence in enumerate(node["evidence"]):
            original = args.corpus / evidence["path"]
            if sha(original) != evidence["source_sha256"]:
                raise ValueError("source drift")
            text = "\n".join(original.read_text().splitlines()[evidence["start"]-1:evidence["end"]])
            instance_atoms.append({"id": family + f":instance-{i+1}", "path": evidence["path"],
                                   "start": evidence["start"], "end": evidence["end"], "sha256": sha(original),
                                   "quote": text, "source_kind": "tutorial"})
        case = node["scope"]["case_directory"].removeprefix("tutorials/")
        field = node["dictionary"]
        questions = [
            f"在blastFoam教程的 {case} 案例中，{field} 这个配置项实际选择了什么？请给出配置位置，并根据手册说明对应模型的用途或适用范围。",
            f"请核对 {case} 教程里的 {field} 设置：实际模型名称是什么、来源在哪，手册对该模型首段的用途或条件说明是什么？不要把配置声明当作已经验证运行条件。",
            f"我在检查 {case} 算例的 {field} 选项。请同时查教程和手册，分别列出实际选择值及位置、对应模型的用途或适用范围，并引用各自原文。",
        ]
        rows.append({"id": family, "category": "cross", "definition_cluster": cluster,
                     "case": case, "field": field, "role": expected, "value": node["value"],
                     "questions": questions, "evidence": [atom, *instance_atoms],
                     "allowed_answer_basis": {"instance_value": node["value"], "manual_definition": explanation},
                     "historical_definition_overlap": definition["historical_definition_overlap"],
                     "historical_instance_overlap": node["historical_instance_overlap"],
                     "status": "draft_requires_8b_fact_and_question_review"})
        decisions.append({"cluster": cluster, "status": "drafted", "role": expected, "selected_node": node["node_id"],
                          "rejected_role_matches": len(group["instances"]) - len(candidates)})
    out = {"schema": "cross-source-fact-drafts-v1", "inventory_sha256": sha(args.inventory),
           "implementation_sha256": sha(Path(__file__)), "frozen": False, "split_assigned": False,
           "cross_draft_families": len(rows), "draft_questions": len(rows) * 3, "families": rows,
           "decisions": decisions, "limits": "首段定义/模型选择任务草案，尚不覆盖全部数字参数、公式、默认值、多文件任务；不是最终规模或独立性证明。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in {"families", "decisions"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
