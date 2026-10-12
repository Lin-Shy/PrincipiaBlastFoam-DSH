"""Compile natural user-need questions into the frozen Chapter 2 QA schema."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


PILOT_IDS = ("UN01", "UN03", "UN06", "UN07", "UN08", "UN09")
FULL_IDS = tuple(f"UN{i:02d}" for i in range(1, 11))

# Fixed before any GN/control answer is generated.  The public question stays
# verbatim; cases, targets, evidence, and scoring points remain evaluation-only.
CURATION = {
    "UN01": {
        "category": "tutorial",
        "family": "natural-building-array-reference",
        "difficulty": "hard",
        "concepts": ["三维建筑几何", "snappyHexMesh", "自适应网格"],
        "cases": ["blastFoam/building3D", "blastFoam/building3DWorkshop"],
        "targets": ["案例选择", "STL几何与网格流程", "适用范围"],
        "gold": [
            "可将building3D或building3DWorkshop中基于STL、snappyHexMesh和自适应加密的三维建筑网格流程作为组成参考。",
            "现有教程是L形单体建筑，不是3×3九个立方体的可直接运行模板；需要另行建立九建筑几何与布局。",
            "现有资料不足以确定新场景的载荷、初始条件和边界条件，也不能声称已经完成建模或验证。",
        ],
        "evidence": ["B1", "B2", "B3", "B4"],
    },
    "UN02": {
        "category": "tutorial",
        "family": "natural-corner-wave-reference",
        "difficulty": "hard",
        "concepts": ["压力波绕角传播", "拐角几何", "条件化案例迁移"],
        "cases": ["blastFoam/building3D", "blastParcelFoam/forwardStep"],
        "targets": ["案例选择", "几何与网格组成参考", "适用范围与待确认条件"],
        "gold": [
            "应先区分管道转弯与外部障碍，并确认介质和二维或三维要求；现有材料只支持条件化参考。",
            "building3D中的L形STL与snappyHexMesh流程可作为壁面几何和网格处理参考，但不能据此声称已有经验证的拐角压力波传播模板。",
            "forwardStep的台阶分块网格也只能作为角点几何参考；该例包含颗粒路线和特定边界，初始压力波、传播边界及验证仍需另行设计。",
        ],
        "evidence": ["B1", "B2", "C1", "C2", "C3"],
    },
    "UN03": {
        "category": "tutorial",
        "family": "natural-fsi-flap-reference",
        "difficulty": "medium",
        "concepts": ["流固耦合", "薄板变形", "压力冲击"],
        "cases": ["blastFSIFoam/flap", "preCICE/flap"],
        "targets": ["案例选择", "材料模型", "外部耦合依赖"],
        "gold": [
            "blastFSIFoam/flap是二维爆炸波与可变形flap相互影响的流固耦合参考，可作为起点。",
            "该案例是二维且求解器说明仍在开发；其linearJohnsonCookPlastic材料参数不能直接代表任意薄板材料。",
            "也可有条件地参考preCICE/CalculiX路线，但它需要相应外部耦合器和固体求解工具，现有README不能证明当前环境已验证。",
        ],
        "evidence": ["F1", "F2", "F4"],
    },
    "UN04": {
        "category": "tutorial",
        "family": "natural-closed-shock-tube-reference",
        "difficulty": "medium",
        "concepts": ["压力间断", "封闭端边界", "近一维与二维"],
        "cases": ["blastFoam/shockTube_tabulated"],
        "targets": ["setFieldsDict初始化", "U和p边界", "blockMeshDict维度"],
        "gold": [
            "shockTube_tabulated通过setFieldsDict给同一气体设置左右不同的压力和密度区域，可作为隔膜撤除后的压力间断起点。",
            "示例网格为500×1×1且非轴向面使用empty，因此实质上是近一维参考；要研究二维传播需要修改网格及相应边界。",
            "两端walls上的速度为noSlip、压力为zeroGradient；应结合几何和字段配置判断封闭端，并以setFieldsDict而不是p.orig占位值核对实际初态。",
        ],
        "evidence": ["S1", "S2", "S3", "S4", "S5"],
    },
    "UN05": {
        "category": "tutorial",
        "family": "natural-tabulated-gas-properties",
        "difficulty": "hard",
        "concepts": ["表格物性", "tabulatedMG", "输入变量兼容性"],
        "cases": ["blastFoam/shockTube_tabulated"],
        "targets": ["phaseProperties模型选择", "p.csv和T.csv", "表格自变量与单位"],
        "gold": [
            "shockTube_tabulated提供了直接入口：选择eTabulated与tabulatedMG，并从constant/p.csv和constant/T.csv读取压力、温度表。",
            "该教程要求压力和温度以密度、内能为自变量；不能把任意气体性质表只改文件名就直接使用。",
            "实施前应先确认表中物理量、自变量、单位、覆盖范围和插值设置；若表是其他变量关系，还需继续查对应状态方程或输运模型说明。",
        ],
        "evidence": ["S1", "T1", "T2"],
    },
    "UN06": {
        "category": "tutorial",
        "family": "natural-inert-particle-reference",
        "difficulty": "medium",
        "concepts": ["拉格朗日颗粒", "颗粒反馈", "无反应"],
        "cases": ["blastParcelFoam/forwardStep", "blastEulerFoam/shockTube_polydisperse"],
        "targets": ["案例选择", "cloudProperties耦合与反应设置", "颗粒表示方式"],
        "gold": [
            "若关注离散颗粒，可参考blastParcelFoam/forwardStep；其thermoCloud当前active、coupled、transient均已开启。",
            "该例当前heatTransfer、phaseChange、devolatilisation和surfaceReaction等设置为none，能够支持无反应起点，但README的heated描述不能代替实际配置核对。",
            "若需要连续颗粒相而不是单颗粒轨迹，可有条件地参考多颗粒相shockTube；开始前应澄清颗粒表示方式、浓度和碰撞需求。",
        ],
        "evidence": ["C1", "P1", "P2", "P4"],
    },
    "UN07": {
        "category": "tutorial",
        "family": "natural-combustible-pipe-reference",
        "difficulty": "hard",
        "concepts": ["可燃气体传播", "点火", "开放与封闭边界"],
        "cases": ["blastXiFoam/deflagrationToDetonationTransition"],
        "targets": ["案例选择", "combustionProperties", "U和p边界"],
        "gold": [
            "deflagrationToDetonationTransition可作为燃烧传播参考，但当前燃料为HydrogenInAir并使用特定火焰速度和Xi模型，不能推广为任意可燃气体。",
            "实际速度边界为inlet noSlip、outlet zeroGradient；压力在inlet和outlet均为zeroGradient，应按字段配置核对用户的封闭端和开放端要求。",
            "仅凭inlet/outlet名称或zeroGradient不能保证理想封闭、无反射开放边界；混合物和目标传播阶段仍需确认。",
        ],
        "evidence": ["R1", "R2", "R3", "R4"],
    },
    "UN08": {
        "category": "tutorial",
        "family": "natural-pressure-probe-output",
        "difficulty": "medium",
        "concepts": ["定点压力时序", "probes", "整场写出"],
        "cases": ["blastFoam/building3DWorkshop", "blastFoam/building3D"],
        "targets": ["controlDict/functions", "pressureProbes", "writeControl和writeInterval"],
        "gold": [
            "可在controlDict的functions中使用probes或blastProbes，设置probeLocations和fields中的p，结果写入postProcessing。",
            "示例中的pressureProbes按timeStep、writeInterval 1记录；探针位置必须在或按实现规则调整到网格内。",
            "探针的写出控制与整场writeControl adjustableRunTime、writeInterval 5e-5是两套设置，减少整场保存不等于取消必要的重启输出。",
        ],
        "evidence": ["O1", "O5", "O6"],
    },
    "UN09": {
        "category": "tutorial",
        "family": "natural-small-timestep-diagnosis",
        "difficulty": "hard",
        "concepts": ["自适应时间步", "Courant数", "自适应网格"],
        "cases": ["blastFoam/building3D"],
        "targets": ["controlDict时间步控制", "dynamicMeshDict加密控制", "日志诊断"],
        "gold": [
            "先检查controlDict中的deltaT、adjustTimeStep、maxCo和maxDeltaT；示例值分别包含1e-7、yes、0.5和1。",
            "若启用了自适应网格，还应检查dynamicMeshDict中的densityGradient、refineInterval、阈值和maxRefinement，因为加密会改变局部网格尺度。",
            "这些设置只能提供排查入口；缺少最后日志、终止信息和当前配置时，不能断言停止的具体原因。",
        ],
        "evidence": ["O2", "D1", "D2"],
    },
    "UN10": {
        "category": "tutorial",
        "family": "natural-vegetation-attenuation-boundary",
        "difficulty": "hard",
        "concepts": ["冲击波衰减", "植物等效建模", "覆盖边界"],
        "cases": ["blastFoam/building3D", "blastFSIFoam/flap"],
        "targets": ["直接案例覆盖判断", "刚性几何组成参考", "变形耦合组成参考"],
        "gold": [
            "现有证据没有给出经过验证的灌木或植被冲击波衰减模板，因此只能说明找到可借用的组成部分，不能断言软件不支持。",
            "若把灌木近似为显式刚性障碍，可借用building3D的STL、snappyHexMesh和自适应网格流程，但植物几何简化及衰减规律需要另行论证和验证。",
            "若需要变形反馈，可参考二维flap的流固耦合框架；该求解器仍在开发且材料模型不是植物模型，应先明确表示方式、尺度、变形需求和验证目标。",
        ],
        "evidence": ["B1", "B2", "F1", "F2"],
    },
}


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    return hashlib.sha256(raw).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def compile_dataset(source, evidence_path, corpus, corpus_manifest, scoring, output, ids):
    if output.exists():
        raise FileExistsError(f"preserve frozen dataset: {output}")
    output.mkdir(parents=True)
    questions_by_id = {row["id"]: row for row in read_jsonl(source)}
    evidence_by_id = {row["id"]: row for row in read_jsonl(evidence_path)}
    manifest = json.loads(corpus_manifest.read_text())
    questions, annotations = [], []
    for item_id in ids:
        if item_id not in CURATION or item_id not in questions_by_id:
            raise ValueError(f"unknown curated item: {item_id}")
        c = CURATION[item_id]
        public = questions_by_id[item_id]["query"]
        forbidden_tokens = [*c["cases"], "tutorials/", "manual/", "controlDict", "dynamicMeshDict"]
        if any(token.casefold() in public.casefold() for token in forbidden_tokens):
            raise ValueError(f"public question leaks private case/path detail: {item_id}")
        questions.append({"id": f"{item_id}-p1", "item_id": item_id, "question": public})
        frozen_evidence = []
        for evidence_id in c["evidence"]:
            old = evidence_by_id[evidence_id]
            path = old["path"]
            if path not in manifest:
                raise ValueError(f"evidence outside formal 702-text corpus: {evidence_id} {path}")
            raw = (corpus / path).read_bytes()
            if sha(raw) != manifest[path]["sha256"]:
                raise ValueError(f"formal corpus drift: {path}")
            lines = raw.decode().splitlines()
            start, end = old["start_line"], old["end_line"]
            quote = "\n".join(lines[start - 1:end])
            if quote != old["quote"]:
                raise ValueError(f"legacy evidence differs from formal corpus: {evidence_id}")
            frozen_evidence.append({
                "id": f"{item_id}:{evidence_id}", "path": path, "start": start, "end": end,
                "source_kind": "tutorial", "sha256": sha(raw), "quote": quote,
                "quote_sha256": sha(quote), "pdf_page": None, "status": "tutorial_observed",
            })
        annotations.append({
            "id": item_id, "split": "dev", "category": c["category"], "family": c["family"],
            "difficulty": c["difficulty"], "intents": ["自然需求", "案例发现", "适用性判断"],
            "concepts": c["concepts"], "cases": c["cases"], "targets": c["targets"],
            "gold": c["gold"],
            "allowed": ["可使用原文充分支持的等价案例或等价表述；不按精确证据ID匹配。"],
            "forbidden": ["把未检索到说成不存在", "声称已经修改、运行或验证", "把参考案例说成可无条件直接照搬"],
            "ambiguity": [], "evidence": frozen_evidence, "required_sources": ["tutorial"],
            "score_rule": "navigation-quality-v1", "origin": questions_by_id[item_id].get("origin"),
        })
    write(output / "dev.questions.json", questions)
    write(output / "dev.annotations.json", annotations)
    shutil.copy2(corpus_manifest, output / "corpus-manifest.json")
    rules = json.loads(scoring.read_text())
    is_pilot = tuple(ids) == PILOT_IDS
    version = "natural-user-needs-pilot-v1" if is_pilot else "natural-user-needs-full-v1"
    rules["dataset_scope"] = "Natural user needs with case, solver, file and answer details hidden from the answering model."
    rules["evaluation_policy"] = (
        "Six items fixed before GN/control generation; development evidence only; expand only after the predeclared pilot comparison."
        if is_pilot else
        "All ten accepted natural needs; expanded only after the frozen pilot showed directional GN improvement."
    )
    write(output / "scoring-rules.json", rules)
    provenance = {
        "schema": "natural-user-needs-pilot-provenance-v1" if is_pilot else "natural-user-needs-full-provenance-v1",
        "selected_ids": list(ids),
        "selection_policy": (
            "UN01 real request plus five accepted natural synthetic requests spanning FSI, particles, combustion, output and diagnosis; fixed before generation."
            if is_pilot else
            "All ten accepted natural-needs source questions, expanded after the predeclared pilot gate passed."
        ),
        "public_question_policy": "Verbatim source queries; no case, solver, file path or target identifier added.",
        "private_annotation_policy": "Case names, targets, evidence and gold remain evaluation-only.",
        "source_files": {
            str(source): sha(source.read_bytes()), str(evidence_path): sha(evidence_path.read_bytes()),
            str(corpus_manifest): sha(corpus_manifest.read_bytes()), str(scoring): sha(scoring.read_bytes()),
        },
        "limitations": [
            f"Only UN01 is a recorded real user request; the other {len(ids) - 1} were author-written and accepted as natural development prompts.",
            "This dataset uses one wording per fact family and is not an unseen benchmark.",
            "All gold evidence is tutorial-side so every cited source is represented in the frozen 702-text corpus.",
        ],
    }
    write(output / "provenance.json", provenance)
    artifacts = {p.name: sha(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()}
    dataset_manifest = {
        "version": version, "split": "dev-only", "observed_development_results": not is_pilot,
        "counts": {"items": len(ids), "questions": len(questions), "categories": {"tutorial": len(ids)}},
        "corpus_id": sha(corpus_manifest.read_bytes()), "source_files": len(manifest),
        "question_information_policy": "Only the verbatim user request is visible; evaluation-only fields contain concrete case information.",
        "expansion_gate": (
            "Expand to the full natural-needs set only after the frozen GN versus no-graph pilot is scored."
            if is_pilot else
            "Passed: pilot GN strict success 27.8% versus no-graph 5.6%; full set frozen after observing this aggregate gate only."
        ),
        "artifacts": artifacts,
    }
    write(output / "manifest.json", dataset_manifest)
    print(wire({"output": str(output), "items": len(ids), "questions": len(questions), "manifest_sha256": sha((output / "manifest.json").read_bytes())}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--corpus-manifest", type=Path, required=True)
    p.add_argument("--scoring-rules", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ids", nargs="*", default=list(PILOT_IDS))
    a = p.parse_args()
    compile_dataset(a.questions.resolve(), a.evidence.resolve(), a.corpus.resolve(),
                    a.corpus_manifest.resolve(), a.scoring_rules.resolve(), a.output.resolve(), tuple(a.ids))


if __name__ == "__main__":
    main()
