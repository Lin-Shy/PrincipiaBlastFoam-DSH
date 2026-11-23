"""Switch-controlled professional system comparison on a new public cavity task."""
import shutil
import sys
from pathlib import Path
import pair_run as runner

VARIANT = sys.argv[2]
if VARIANT not in ("off", "on"):
    raise ValueError("unknown control switch")
SOURCE = Path(__file__).resolve()
OLD = runner.BASE / "openfoam_cavity_pair100_20261122/professional/professional"
runner.ARM = "professional"
runner.STUDY = runner.BASE / "delivery_controls_live100_20261122"
runner.PAIR = runner.STUDY / VARIANT
runner.ROOT = runner.PAIR / "professional"
runner.RID = "c3-delivery-controls-" + VARIANT + "-20261122"
runner.TASK = (runner.TASK.replace("12×12×1（144单元）", "14×14×1（196单元）")
               .replace("0.0025", "0.002").replace("0.25", "0.3")
               .replace("0.05", "0.04").replace("144单元", "196单元")
               + "\n本次会话最多50次模型请求，无续跑。\n")


def prepare():
    pair, root = runner.PAIR, runner.ROOT
    pair.mkdir(exist_ok=False)
    for name in ("workspace/common", "workspace/delivery", "home", "tmp", "user", "cache", "agents_home"):
        (root / name).mkdir(parents=True)
    shutil.copytree(OLD / "skills", root / "skills")
    shutil.copytree(runner.REFERENCE / "payload/case", root / "workspace/case")
    shutil.copyfile(runner.SRC / "client.py", root / "workspace/common/client.py")
    (root / "workspace/TASK.md").write_text(runner.TASK, encoding="utf8")
    (root / "prompt.txt").write_text("完成 TASK.md，在当前工作区自主修改、登记、回收和交付。", encoding="utf8")
    config = (OLD / "dump.yml").read_text(encoding="utf8").replace(str(OLD), str(root))
    if VARIANT == "on":
        config += "\n- id: delivery-controls\n  name: " + (runner.SRC.parent / "delivery-controls.mjs").as_uri() + "\n"
    (root / "dump.yml").write_text(config, encoding="utf8")
    runner.write(pair / "protocol.json", dict(task="CAVITY-MOD-04", variant=VARIANT,
        controls_enabled=VARIANT == "on", arm="professional", max_requests=50,
        retries=0, jobs=1, node_minutes=5,
        source_plan_sha256=runner.sha(runner.REFERENCE / "plan.json"),
        design_sha256=runner.sha(runner.wave.WS / "graduation-thesis-materials/graduation-research/chapters/chapter03.md"),
        exposure="public developed cavity family; not an unseen test",
        acceptance="same strict complete-delivery criteria, numerical verification, README replay; extra claims separately audited"))
    pins = [SOURCE, runner.SRC / "pair_run.py", runner.SRC / "client.py",
            runner.STUDY / "protocol.json", pair / "protocol.json", root / "dump.yml", root / "prompt.txt",
            runner.REFERENCE / "payload/run_case.sh", runner.SRC.parent.parent / "launch_attempt.py",
            runner.SRC.parent.parent / "native_attempt.mjs", runner.SRC.parent / "measurement-audit.mjs",
            runner.SRC.parent / "delivery-controls.mjs", runner.SRC.parent / "delivery-check-core.mjs",
            *[p for p in (root / "workspace").rglob("*") if p.is_file()],
            *(root / "skills").rglob("SKILL.md")]
    runner.write(pair / "manifest.json", dict(source_sha256={str(p): runner.sha(p) for p in pins}))


if __name__ == "__main__":
    {"prepare": prepare, "agent": runner.agent, "operator": runner.operator}[sys.argv[1]]()
