"""New public-contract whole-system comparison; historical tasks stay frozen."""
from pathlib import Path
import shutil
import sys
import pair_run as runner

SOURCE = Path(__file__).resolve()
runner.STUDY = runner.BASE / "delivery_contract_pair100_20261122"
runner.PAIR = runner.STUDY / runner.ARM
runner.ROOT = runner.PAIR / runner.ARM
runner.RID = "c3-contract-pair-" + runner.ARM + "-20261122"
PUBLIC_IDENTITY = """
公开交付身份条件：delivery/case/的八份输入须与exchange/request.json中登记的对应文本一致，按UTF-8表示且仅允许CRLF/LF换行差异，头部、注释及其他排版也须保留。不得用节点写回版本替换登记输入，即使物理条件相同。
delivery/native/须按原始字节保留回收文件。receipt.files中的case/0/U指exchange/native/case/0/U（交付后为delivery/native/case/0/U），不是登记输入case/0/U；节点初始化可以改写初始场。receipt.input_sha256是登记JSON整体哈希，不是某个输入的哈希。
客户端显示的registered_inputs与recovered_native分别标识这两套文件来源和哈希；实际回执仍为exchange/receipt.json。客户端不生成交件、不替你验证原生文件完整性或数值。路径、输入身份、原生结果、后处理摘要和README各自必须满足题面，不能相互替代。
本次会话最多50次模型请求，无续跑。仅使用本次工作区公开输入及本臂工具/技能，不读取其他实验、历史答案或评分材料。
"""
runner.TASK = (runner.TASK.replace("12×12×1（144单元）", "18×18×1（324单元）")
               .replace("0.0025", "0.0015").replace("0.25", "0.35")
               .replace("0.05", "0.03").replace("144单元", "324单元")
               + PUBLIC_IDENTITY)


def freeze():
    runner.STUDY.mkdir(exist_ok=False)
    runner.write(runner.STUDY / "protocol.json", dict(
        task="CAVITY-MOD-05", order=["general", "professional"],
        comparison="Whole original DSH versus professional system; identical newly disclosed contract and role-labelled client in both arms",
        total_requests=100, per_arm=50, retries=0, transfer=False,
        jobs_per_arm=1, minutes_per_job=5, model="deepseek-v4.1-flash",
        parameters=dict(cells=324, mesh=[18,18,1], lid_m_s=0.35, dt=0.0015, end=0.03, write_interval=10),
        primary="Existing strict complete-delivery criteria: eight registered input texts with CRLF normalized to LF only; complete original native case/logs; matching receipt; postprocess.py, four correct summary metrics and README replay; requested settings,20steps,finite fields",
        numerical_tolerance=1e-8, scoring_rule_changed=False,
        public_information_change="Both arms now explicitly receive existing exact-input-text identity, native-file hash root and whole-registration hash meaning, plus separate computed input/native hash maps from candidate client",
        secondary=["requests and reported tokens", "node state and elapsed time", "input-copy and hash-comparison actions", "README and path completeness", "extra claims", "actual read scope", "receipt provenance and independent replay"],
        selection="Predeclared next parameter variant in already exposed public cavity development family; no result selection",
        budget_basis="Prior genuine complete paths used40-50 requests; equal50 caps permit whole-system comparison without transferring unused budget",
        delivery_controls_enabled=False, automatic_delivery=False,
        independent_review="Preflight binding and post-seal independent validation; never fill missing model files",
        limitations=["one paired public development task", "fixed general-first order", "same-host access audited, not OS confinement", "whole-system comparison, not isolated client treatment effect", "no retrospective change to old results", "no physical prediction accuracy reference"],
        design_sha256=runner.sha(runner.wave.WS / "graduation-thesis-materials/graduation-research/chapters/chapter03.md"),
        prior_audit_index_sha256=runner.sha(runner.BASE / "delivery_contract_audit_20261122/index.json")))


def prepare():
    runner.PAIR.mkdir(exist_ok=False)
    root = runner.ROOT
    for name in ("workspace/common", "workspace/delivery", "home", "tmp", "user", "cache", "agents_home"):
        (root / name).mkdir(parents=True)
    # Reuse the same already-tested profiles and old professional skills as MOD-02.
    old = runner.BASE / "openfoam_cavity_pair100_20261122" / runner.ARM / runner.ARM
    shutil.copytree(old / "skills", root / "skills")
    shutil.copytree(runner.REFERENCE / "payload/case", root / "workspace/case")
    shutil.copyfile(runner.SRC / "contract_client.py", root / "workspace/common/client.py")
    (root / "workspace/TASK.md").write_text(runner.TASK, encoding="utf8")
    (root / "prompt.txt").write_text("完成 TASK.md，在当前工作区自主修改、登记、回收和交付。", encoding="utf8")
    config = (old / "dump.yml").read_text(encoding="utf8").replace(str(old), str(root))
    assert "delivery-controls" not in config
    (root / "dump.yml").write_text(config, encoding="utf8")
    runner.write(runner.PAIR / "protocol.json", dict(task="CAVITY-MOD-05", arm=runner.ARM,
        max_requests=50, retries=0, jobs=1, node_minutes=5,
        study_protocol_sha256=runner.sha(runner.STUDY / "protocol.json"),
        client_sha256=runner.sha(runner.SRC / "contract_client.py"),
        task_sha256=runner.sha(root / "workspace/TASK.md")))
    pins = [SOURCE, runner.SRC / "pair_run.py", runner.SRC / "contract_client.py",
            runner.SRC / "pair_verify.py", runner.STUDY / "protocol.json", runner.PAIR / "protocol.json",
            root / "dump.yml", root / "prompt.txt", runner.REFERENCE / "payload/run_case.sh",
            runner.SRC.parent.parent / "launch_attempt.py", runner.SRC.parent.parent / "native_attempt.mjs",
            runner.SRC.parent / "measurement-audit.mjs",
            *[p for p in (root / "workspace").rglob("*") if p.is_file()],
            *(root / "skills").rglob("SKILL.md")]
    runner.write(runner.PAIR / "manifest.json", dict(source_sha256={str(p): runner.sha(p) for p in pins}))


if __name__ == "__main__":
    {"freeze": freeze, "prepare": prepare, "agent": runner.agent, "operator": runner.operator}[sys.argv[1]]()
