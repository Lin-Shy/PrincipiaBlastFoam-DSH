"""评分侧扩展数据草案的参数、公式、默认值、多文件及单来源覆盖。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re


PARAMETERS = {
    8: ["gas/air/thermodynamics/Cv", "gas/products/thermodynamics/Cv"],
    9: ["c4/products/thermodynamics/CvCoeffs<8>"],
    10: ["particles/equationOfState/rho0"],
    11: ["air/equationOfState/a", "air/equationOfState/gamma"],
    12: ["c4/products/equationOfState/A", "c4/products/equationOfState/rho0"],
    14: ["gas/air/equationOfState/b", "gas/products/equationOfState/b"],
    15: ["c4/reactants/equationOfState/K0", "c4/reactants/equationOfState/pRef"],
    16: ["c4/reactants/equationOfState/K0", "c4/reactants/equationOfState/K0Prime"],
    17: ["gas/air/transport/mu", "gas/air/transport/Pr"],
    18: ["RDX/initiation/vDet", "RDX/initiation/burnModel"],
    19: ["c4/initiation/I", "c4/initiation/minLambda2"],
    21: ["gas/constantDiameterCoeffs/d"],
}
MANUAL_REFERENCES = [("03_interfacial_models.md", 37), ("03_interfacial_models.md", 57),
                     ("03_interfacial_models.md", 219), ("04_granular_models.md", 84),
                     ("05_fluid_solid_thermo.md", 424), ("05_fluid_solid_thermo.md", 979)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--drafts", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--graph", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("new version required")
    draft = json.loads(args.drafts.read_text())
    inventory = json.loads(args.inventory.read_text())
    graph = json.loads(args.graph.read_text())
    rows = copy.deepcopy(draft["families"])

    def atom(path, start, end, identity):
        file = args.corpus / path
        lines = file.read_text().splitlines()
        if not 1 <= start <= end <= len(lines):
            raise ValueError("invalid source coordinates")
        return {"id": identity, "path": path, "start": start, "end": end,
                "sha256": sha(file), "quote": "\n".join(lines[start-1:end]),
                "source_kind": "manual" if path.startswith("manual/") else "tutorial"}

    for f in rows:
        f["task_types"] = ["model_selection_definition"]
        f["ambiguities"] = []
        num = int(f["id"].rsplit("-", 1)[1])
        if num in PARAMETERS:
            definition = inventory["cross_candidates"][f["definition_cluster"]]["definition"]
            manual_lines = (args.corpus / definition["path"]).read_text().splitlines()
            section_range = range(definition["start"], definition["end"]+1)
            formula_marks = [i for i in section_range if manual_lines[i-1].strip() == "$$"]
            if formula_marks:
                begin, finish = formula_marks[:2]
                f["evidence"].append(atom(definition["path"], begin, finish, f["id"] + ":first-formula"))
                cursor = finish + 1
                while cursor <= definition["end"] and (not manual_lines[cursor-1].strip() or re.fullmatch(r"\([\d.]+\)", manual_lines[cursor-1].strip())):
                    cursor += 1
                if cursor <= definition["end"] and manual_lines[cursor-1].lstrip().startswith("where "):
                    last = cursor
                    while last < definition["end"] and manual_lines[last].strip():
                        last += 1
                    f["evidence"].append(atom(definition["path"], cursor, last, f["id"] + ":formula-variables"))
            required_keys = {field.rsplit("/", 1)[-1] for field in PARAMETERS[num]}
            if num == 8:
                required_keys.add("Tref")
            if num == 10:
                required_keys.add("pRef")
            if num == 15:
                required_keys.add("kappa")
            normalize = lambda s: re.sub(r"[^a-z0-9]", "", s.casefold())
            table_rows = [i for i in section_range if manual_lines[i-1].lstrip().startswith("|") and
                          normalize(manual_lines[i-1].split("|")[1]) in {normalize(k) for k in required_keys}]
            for i in table_rows:
                f["evidence"].append(atom(definition["path"], i, i, f["id"] + f":manual-row-{i}"))
            f["task_types"] += ["actual_parameter_definition_units", "formula_or_condition"]
            f["parameter_facts"] = []
            for field in PARAMETERS[num]:
                nodes = [n for n in graph["nodes"].values() if n["kind"] == "configuration" and n["path"] == f["evidence"][1]["path"] and n.get("dictionary") == field]
                if len(nodes) != 1:
                    raise ValueError("ambiguous parameter selection: " + field)
                node = nodes[0]
                evidence = node["evidence"][0]
                f["evidence"].append(atom(evidence["path"], evidence["start"], evidence["end"], f["id"] + ":" + field))
                f["parameter_facts"].append({"field": field, "value": node["value"]})
            fields = "、".join(PARAMETERS[num])
            extra = f"另外请核对 {fields} 的实际配置值、手册中的含义和单位，并说明本节首个公式（若有）与这些参数的对应关系；本节没有公式时说明模型用途，手册未明确给出的单位不要猜测。"
            if num == 8:
                extra += "同时区分Tref的手册默认值与教程已写出的参数，不把默认当成实例显式配置。"
                f["task_types"].append("default_vs_instance")
            if num == 10:
                extra += "手册正文与表格对pRef默认值的说明若不一致，请分别报告并指出歧义，不能任选其一。"
                f["ambiguities"].append("手册正文默认参考压力0 Pa，表格却写101235 Pa；不裁定运行实现。")
                f["task_types"].append("default_source_conflict")
            if num == 14:
                extra += "请以AbelNobel节标题和公式为依据；该节说明句提到BKW时应注明原文混称，不能把教程选项改写成BKW。"
                extra += "教程b行的注释与手册b定义若不同，也分别注明原文说法。"
                f["ambiguities"].append("AbelNobel说明句混称BKW，以原始节标题和式5.68的对应作为本题边界。")
                f["ambiguities"].append("教程b的行尾注释写Heat capactiy ratio，手册定义为co-volume；保留并分别报告。")
            if num == 15:
                extra += "K0的实例取值只作为配置事实报告，不据此断言物理设置正确或求解可运行。"
            if num == 19:
                extra += "同时给出minLambda2的手册默认值，和此处显式值分别列出。"
                f["task_types"].append("default_vs_instance")
            f["questions"] = [q + extra for q in f["questions"]]
            f["allowed_answer_basis"]["parameter_facts"] = f["parameter_facts"]
            f["allowed_answer_basis"]["manual_required_ranges"] = [e for e in f["evidence"] if e["source_kind"] == "manual"]
        if 32 <= num <= 38:
            path = "tutorials/" + f["case"] + "/Allrun"
            lines = (args.corpus / path).read_text().splitlines()
            commands = [i for i, line in enumerate(lines, 1) if not line.lstrip().startswith("#") and
                        ("$(getApplication)" in line or f["value"] in line and line.lstrip().startswith(("runParallel ", "runApplication ")))]
            if len(commands) != 1:
                raise ValueError("ambiguous launch command: " + path)
            i = commands[0]
            f["evidence"].append(atom(path, i, i, f["id"] + ":Allrun"))
            f["task_types"].append("multiple_tutorial_files_and_concept")
            extra = "同时报告该案例Allrun中运行算例的命令原文，并与配置声明分开引用；保留动态命令写法，不声称已经执行或解析了外部RunFunctions。"
            f["questions"] = [q + extra for q in f["questions"]]
            f["allowed_answer_basis"]["launch_command"] = lines[i-1]

    for pos, (name, start) in enumerate(MANUAL_REFERENCES, 1):
        definitions = [d for d in inventory["single_source_manual_candidates"] if Path(d["path"]).name == name and d["start"] == start]
        if len(definitions) != 1:
            raise ValueError("manual reference unavailable or historically annotated")
        definition = definitions[0]
        fid = f"draft-manual-{pos:03d}"
        title = definition["title"]
        questions = [f"只查blastFoam手册的 {title} 小节：该模型的用途或适用条件是什么，首个公式如何写、原文明确给出的相关变量说明是什么？请按原文说明，不推断教程是否采用。",
                     f"请根据blastFoam手册 {title} 小节解释模型的用途或条件，并列出本节第一个公式及原文明确给出的变量说明。",
                     f"我需要核对手册 {title} 的定义：请给出用途或适用范围、首个公式和原文有写出的变量解释，并引用准确来源。"]
        manual_lines = (args.corpus / definition["path"]).read_text().splitlines()
        first_formula = [i for i in range(start, definition["end"]+1) if manual_lines[i-1].strip() == "$$"]
        if len(first_formula) < 2:
            raise ValueError("manual reference has no closed first formula")
        begin, finish = first_formula[:2]
        required = [atom(definition["path"], start, begin-1, fid + ":purpose"),
                    atom(definition["path"], begin, finish, fid + ":first-formula")]
        cursor = finish + 1
        while cursor <= definition["end"] and (not manual_lines[cursor-1].strip() or re.fullmatch(r"\([\d.]+\)", manual_lines[cursor-1].strip())):
            cursor += 1
        if cursor <= definition["end"] and manual_lines[cursor-1].lstrip().startswith("where "):
            last = cursor
            while last < definition["end"] and manual_lines[last].strip():
                last += 1
            required.append(atom(definition["path"], cursor, last, fid + ":variables"))
            # WenYu's variable paragraph explicitly leads into the Reynolds-number formula.
            if pos == 1:
                required.append(atom(definition["path"], first_formula[2], first_formula[3], fid + ":variable-formula"))
        table_keys = {5: {"a", "b", "gamma"}, 6: {"mu0", "tref", "c1", "c2"}}.get(pos, set())
        for i in range(start, definition["end"]+1):
            line = manual_lines[i-1]
            if line.lstrip().startswith("|") and re.sub(r"[^a-z0-9]", "", line.split("|")[1].casefold()) in table_keys:
                required.append(atom(definition["path"], i, i, fid + f":variable-row-{i}"))
        ambiguity = ["Tait节标题与正文stiffened EOS措辞不同，保留原文差异，不推断代码实现。"] if pos == 5 else []
        if pos == 5:
            questions = [q + "若本节标题与正文模型名称不同，请分别说明原文称谓。" for q in questions]
        rows.append({"id": fid, "category": "manual", "definition_cluster": definition["path"] + ":" + str(start),
                     "case": "", "field": title, "role": "manual_reference", "value": title,
                     "questions": questions, "evidence": required,
                     "task_types": ["single_source_reference", "formula_or_condition"], "ambiguities": ambiguity,
                     "historical_definition_overlap": [], "historical_instance_overlap": [],
                     "allowed_answer_basis": {"manual_required_ranges": required},
                     "status": "draft_requires_8b_fact_and_question_review"})
    tutorial_specs = [
        ("solids4Foam/flap", "constant/solid/mechanicalProperties", "mechanical/rubber中的type、rho、E、nu以及planeStress开关", "planeStress", ");"),
        ("blastEquation/planarWall", "diffusionProperties", "minimizationCoeffs中的solver、maxSteps、tolerance、nParticles", "minimizationCoeffs", "}"),
    ]
    for pos, (case, file, target, first, last) in enumerate(tutorial_specs, 1):
        path = f"tutorials/{case}/{file}"
        lines = (args.corpus / path).read_text().splitlines()
        start = next(i for i, line in enumerate(lines, 1) if line.strip().startswith(first))
        end = next(i for i, line in enumerate(lines, 1) if i > start and line.strip() == last)
        fid = f"draft-tutorial-{pos:03d}"
        questions = [f"只查 {case} 教程：请核对 {file} 文件里{target}的实际配置，逐项列出取值和位置，不推断运行是否成功。",
                     f"在 {case} 案例中，{file} 的{target}分别写成什么？请依据教程原文回答并引用准确行段。",
                     f"我想检查 {case} 的 {file} 设置，请按教程实际内容列出{target}，不要把注释示例或其他案例取值作为当前值。"]
        rows.append({"id": fid, "category": "tutorial", "definition_cluster": path + ":" + str(start),
                     "case": case, "field": target, "role": "tutorial_reference", "value": "see authoritative configuration",
                     "questions": questions, "evidence": [atom(path, start, end, fid + ":tutorial")],
                     "task_types": ["single_source_reference", "actual_parameter_values"], "ambiguities": [],
                     "historical_definition_overlap": [], "historical_instance_overlap": [],
                     "allowed_answer_basis": {"tutorial_values": "\n".join(lines[start-1:end])},
                     "status": "draft_requires_8b_fact_and_question_review"})
    out = {"schema": "expanded-fact-drafts-v1", "parent_drafts_sha256": sha(args.drafts),
           "inventory_sha256": sha(args.inventory), "graph_sha256": sha(args.graph),
           "implementation_sha256": sha(Path(__file__)), "frozen": False, "split_assigned": False,
           "families": rows, "questions": len(rows)*3,
           "limits": "扩充后的事实组合必须重新复核并审计历史曝光、近重复及独立性；先前复核不能自动迁移。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"families": len(rows), "questions": len(rows)*3, "frozen": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
