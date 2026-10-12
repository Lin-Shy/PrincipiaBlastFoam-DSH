"""数据作者的可追溯近重复审计；不是模型裁决或人工盲审记录。"""
import argparse
import hashlib
import json
from pathlib import Path
import re


# 数据审计记录，禁止用于生产构图或检索。
RATIONALES = [
    "SinclairJackson单粒径条件与旧Gao多粒径定义不同；新增具体教程径向分布选择与该定义的对应。",
    "Lebowitz与Gao同属多粒径径向分布主题，但具体模型身份不同；新题要求Lebowitz实例选择与该节说明。",
    "Syamlal颗粒导热率角色不同于旧拖曳/换热模型与固体各向异性导热；不按同姓或conductivity词合并。",
    "Huilin是granularPressureModel，不是旧Gao radialModel；同为多粒径条件不足以判相同事实。",
    "Lun颗粒压力模型实例与定义，旧标注未要求该模型。",
    "JohnsonJackson摩擦应力平滑压力说明与实例，旧标注未要求该模型。",
    "YuStandish packingLimitModel的粒径排序条件，不能等同旧六相组成或eTabulated。",
    "eConst的常量Cv实例、公式与明确Tref默认值；旧ePower是温度幂律且默认未明示，存在参数主题共享。",
    "ePolynomial的八项CvCoeffs与多项式式，不能等同旧ePower的幂指数C0/n0式。",
    "rhoConst具体颗粒rho0与pRef正文/表格冲突；共享旧固相恒密度约束，但新增实例和冲突。",
    "stiffenedGas的a/gamma和参考压力项；不能把不同式的旧idealGas直接判完整重复，gamma是共享组件。",
    "JWL产品EOS的A/rho0与首式，对应旧题未要求的产品状态方程组合。",
    "perfectGas原文称standard ideal gas relation；虽非恒定比热比说明不同，为避免与旧idealGas的概念别名争议，保守排除。",
    "AbelNobel的b、co-volume与两侧原文混称/注释歧义，旧标注未要求此组合。",
    "Murnaghan名称在旧twoCharge选择器题出现；本题新增flap实例K0/pRef、公式、单位，不把零K0当运行有效。",
    "BirchMurnaghan3名称在旧twoCharge选择器题出现；新增building3D反应物K0/K0Prime与首式对应。",
    "const transport在旧查表案例选择出现；新增另一案例gas组分mu/Pr与黏度首式和单位。",
    "programmedIgnition同案例选择曾在旧README冲突题出现；新增vDet/burnModel和该模型公式定义，不重问旧delays/radii。",
    "pressureBased起爆名称曾在旧选择器题出现；新增flap I/minLambda2实际值与手册默认值；不同于旧粒径reactionRate角色。",
    "field burstModel的含义不同于旧pressure与pressureAndImpulse字段组合。",
    "constantDiameter固定直径和实例d不同于旧constantMass的质量约束/d0公式，也不同于旧reacting输运。",
    "AUSM+通量选择与定义不是旧HLLC接触波解释。",
    "Kurganov通量选择与定义不是旧HLLC接触波解释。",
    "Riemann名称曾在旧lambda离散配置出现；新增gas/Yi对流字段和该节离散方法说明，保留共享方法组件。",
    "Euler时间积分声明与对应说明，不混作速度重构或旧HLLC算法。",
    "RK2SSP具体时间积分声明与该节说明，旧必要标注未要求此组合。",
    "RK4SSP在旧movingCone方案题出现；新增另一案例声明与RK4SSP专节方法说明，旧题只要求HLL/HLLC定义。",
    "delta误差估计器不同于旧densityGradient、cellSize和fieldValue。",
    "vtkTimeSeries是surfaceFormat说明与实际选择，和旧createTimeSeries命令路径策略有系列文件主题共享但角色不同。",
    "setRefinedFields旧README问调试选项；新题是application选择与手册用途定义，披露工具身份组件共享。",
    "initializeAtmosphere旧题问hydrostatic/table配置；新增application声明与工具用途说明，不重问旧pRef数值。",
    "blastFoam的application/Allrun命令与求解器手册用途组合，旧脚本网格顺序题未要求该定义。",
    "blastEulerFoam的application/Allrun命令与Euler多相求解器定义，不重问旧六相组成。",
    "blastFSIFoam与旧FSI情境及网格脚本共享求解器身份；新增building3D声明/原始命令/手册求解器定义的必要组合。",
    "blastXiFoam应用声明、原始命令与求解器说明，不重问旧Su两个文件。",
    "blastReactingFoam应用声明、原始命令与求解器说明，不重问旧obliqueShock U边界值。",
    "blastParcelFoam应用声明、原始命令与求解器说明，不重问旧forwardStep云注入参数。",
    "blastEquation应用声明、原始命令与求解器说明，旧标注未要求该组合。",
    "WenYu单模型首式及其加权Re定义；旧GidaspowErgunWenYu只要求稀/密组合与实例，存在组件主题共享。",
    "Ergun单模型首式；旧GidaspowErgunWenYu只要求稀/密组合与实例，存在组件主题共享。",
    "GelperinEinstein努塞尔关系与旧RanzMarshall/Gunn选择和运行时选择说明不同。",
    "Gidaspow黏度模型角色不同于旧GidaspowErgunWenYu拖曳，不能按同名合并。",
    "Tait正文与stiffened EOS称谓及可重参数化压力式可能与新stiffenedGas主题接近；为避免跨集合别名争议，保守排除。",
    "WLF聚合物黏度首式及变量不同于旧sutherland气体黏度式。",
    "solids4Foam/flap力学参数与planeStress原始配置，不等同旧blastFSIFoam/flap README情境。",
    "planarWall minimization实际solver/maxSteps/tolerance/nParticles，不等同旧通用rootSolver容差与默认值。",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument("--historical-dataset", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new audit version required")
    families = json.loads(args.drafts.read_text())["families"]
    if len(families) != len(RATIONALES):
        raise ValueError("author audit bound to the reviewed 46-family pool")
    history, historical_hashes = [], {}
    for split in ("dev", "holdout"):
        file = args.historical_dataset / (split + ".annotations.json")
        history.extend(json.loads(file.read_text()))
        historical_hashes[file.name] = sha(file)
    rows, signatures = [], set()
    excluded = {"draft-cross-013", "draft-manual-005"}
    for family, reason in zip(families, RATIONALES):
        signature = (family["role"], family["definition_cluster"], family["case"], family["field"])
        if signature in signatures:
            raise ValueError("duplicate candidate task signature")
        signatures.add(signature)
        for atom in family["evidence"]:
            file = args.corpus / atom["path"]
            if sha(file) != atom["sha256"] or "\n".join(file.read_text().splitlines()[atom["start"]-1:atom["end"]]) != atom["quote"]:
                raise ValueError("source drift")
        pairs = []
        for old in history:
            overlaps = [{"new_atom": n["id"], "old_atom": o["id"]} for n in family["evidence"] for o in old["evidence"]
                        if n["path"] == o["path"] and n["start"] <= o["end"] and n["end"] >= o["start"]]
            identifier = str(family["value"])
            mentioned = bool(len(identifier) > 2 and re.search(r"(?<![A-Za-z0-9_])" + re.escape(identifier) + r"(?![A-Za-z0-9_])",
                             " ".join(old["gold"] + old["concepts"]), re.I))
            pairs.append({"historical_family": old["id"], "necessary_range_overlap": overlaps,
                          "selected_model_mentioned_in_gold": mentioned})
        rows.append({"id": family["id"], "decision": "exclude_conservatively" if family["id"] in excluded else "author_assessed_new_combination",
                     "rationale": reason, "all_50_prior_comparisons": pairs,
                     "new_definition_cluster": family["definition_cluster"], "role": family["role"],
                     "source_evidence": family["evidence"]})
    out = {"schema": "source-bound-author-semantic-data-audit-v1", "drafts_sha256": sha(args.drafts),
           "historical_annotations_sha256": historical_hashes, "implementation_sha256": sha(Path(__file__)),
           "audit_kind": "data_author_annotation_with_deterministic_source_checks", "human_blind_review": False,
           "retained_families": len(rows)-len(excluded), "excluded_families": sorted(excluded), "rows": rows,
           "limits": "作者按当前50族标注与公开原文审计新组合，不证明历史从未见过、模型知识独立或事实族之间完全无相关；不把不可靠8B近重复意见升级为裁决。正式报告披露共享组件与曝光，人工盲审另行执行。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"retained": out["retained_families"], "excluded": out["excluded_families"], "human_blind_review": False}))


if __name__ == "__main__":
    main()
