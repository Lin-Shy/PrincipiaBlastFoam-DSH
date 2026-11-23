"""Dispatch only the released public startup-Couette package through normal DSH.

Usage: run.py freeze|prepare|agent|operator general|professional RELEASE_JSON
The release path is explicit, never inferred from directory timestamps.
"""
from pathlib import Path
import shutil
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cavity_agent"))
import pair_run as runner

SOURCE = Path(__file__).resolve()
RELEASE = Path(sys.argv[3]).resolve()
DATA = runner.wave.WS / "graduation-datasets/chapter03_simulation_tasks/couette_start_20261122"
assert RELEASE.is_relative_to(DATA.resolve())
runner.STUDY = runner.BASE / "startup_couette_pair100_20261122"
runner.PAIR = runner.STUDY / runner.ARM
runner.ROOT = runner.PAIR / runner.ARM
runner.RID = "c3-startup-couette-" + runner.ARM + "-20261122"


def checked_release():
    current = runner.read(DATA / "CURRENT.json")
    assert RELEASE == (DATA / current["release"]).resolve()
    assert runner.sha(RELEASE) == current["release_sha256"]
    release = runner.read(RELEASE)
    assert release["task_id"] == "COUETTE-START01" and release["dispatch_allowed"] is True
    archive = (DATA / release["public_archive"]).resolve()
    assert archive.is_relative_to(DATA.resolve())
    assert runner.sha(archive) == release["public_sha256"]
    assert all(runner.sha(DATA / name) == digest for name, digest in release["files"].items())
    with zipfile.ZipFile(archive) as package:
        assert set(package.namelist()) == {"TASK.md", "settings.json"}
        task = package.read("TASK.md").decode("utf8")
        assert "ASCII" in task and "receipt.json" in task
    return release, archive


def freeze():
    release, archive = checked_release()
    runner.STUDY.mkdir(exist_ok=False)
    runner.write(runner.STUDY / "protocol.json", dict(
        task="COUETTE-START01", public_version=release["version"],
        release_path=str(RELEASE.relative_to(runner.wave.WS)), release_sha256=runner.sha(RELEASE),
        public_archive=str(archive.relative_to(runner.wave.WS)), public_sha256=release["public_sha256"],
        comparison="Original DSH versus professional system, from empty case, identical released task and base node interface",
        order=["general", "professional"], total_requests=100, per_arm=50, retries=0, transfer=False,
        jobs_per_arm=1, minutes_per_job=5, model="deepseek-v4.1-flash",
        budget_basis="New independent100-request batch;50 per arm permits from-scratch dictionaries and profile readout; all failed requests count, no inherited unused allowance",
        primary="Complete sealed delivery, registered text identity, original native provenance, prescribed transient configuration, two-time profile and summary, independent analytic tolerance and clean README replay",
        acceptance_source_sha256=runner.sha(DATA / "grading/definition.json"),
        acceptance_implementation_sha256=runner.sha(DATA / "grading/grade.py"),
        profile_max_abs_error_m_s=0.002, reconstruction_abs_tolerance=1e-10,
        transverse_and_x_spread_max_m_s=1e-6,
        exposure="New transient goal in previously developed plane-shear background; not a held-out family or physical measurement prediction test",
        maintenance_readiness=dict(job_id="9264449", node_jobs=1, node_seconds=4, model_requests=0,
            excluded_from_agent_denominator=True,
            archive_sha256=runner.sha(runner.BASE / "cross_family_preparation_20261122/operator-readiness/operator/collected.tar")),
        delivery_controls_enabled=False, automatic_delivery=False, default_client_replaced=False,
        secondary=["actual model requests and missing usage", "node state and runtime", "source reads and registration/collection actions", "configuration and reconstruction defects", "extra physical claims"],
        limitations=["one new development task", "fixed order", "same-host access audited, no OS confinement",
            "whole-system comparison, not single-client causal effect", "prior local numeric-precheck deviation preserved and excluded from engineering evidence"],
        design_sha256=runner.sha(runner.wave.WS / "graduation-thesis-materials/graduation-research/chapters/chapter03.md")))


def prepare():
    release, archive = checked_release()
    assert runner.read(runner.STUDY / "protocol.json")["release_sha256"] == runner.sha(RELEASE)
    runner.PAIR.mkdir(exist_ok=False)
    root = runner.ROOT
    for name in ("workspace/common", "workspace/case", "workspace/delivery", "home", "tmp", "user", "cache", "agents_home"):
        (root / name).mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        for name in ("TASK.md", "settings.json"):
            (root / "workspace" / name).write_bytes(package.read(name))
    old = runner.BASE / "delivery_contract_pair100_20261122" / runner.ARM / runner.ARM
    shutil.copytree(old / "skills", root / "skills")
    shutil.copyfile(HERE / "client.py", root / "workspace/common/client.py")
    shutil.copyfile(runner.SRC / "contract_client.py", root / "workspace/common/contract_client.py")
    (root / "prompt.txt").write_text(
        "独立完成TASK.md和settings.json中的任务，从空case/创建工程。基础接口为python common/client.py submit及collect，输入只能登记一次，未就绪可重复collect。最多50次模型请求，无续跑。只使用本工作区公开输入及本臂工具/技能，不读取其他实验、历史答案或评分材料。禁止本地求解。", encoding="utf8")
    config = (old / "dump.yml").read_text(encoding="utf8").replace(str(old), str(root))
    assert "delivery-controls" not in config
    (root / "dump.yml").write_text(config, encoding="utf8")
    runner.write(runner.PAIR / "protocol.json", dict(task="COUETTE-START01", arm=runner.ARM,
        study_protocol_sha256=runner.sha(runner.STUDY / "protocol.json"), max_requests=50,
        retries=0, jobs=1, node_minutes=5, public_sha256=release["public_sha256"], starting_case_empty=True))
    pins = [SOURCE, HERE / "client.py", RELEASE, archive,
        runner.SRC / "contract_client.py", runner.SRC / "pair_run.py",
        runner.STUDY / "protocol.json", runner.PAIR / "protocol.json", root / "dump.yml", root / "prompt.txt",
        runner.REFERENCE / "payload/run_case.sh", runner.SRC.parent.parent / "launch_attempt.py",
        runner.SRC.parent.parent / "native_attempt.mjs", runner.SRC.parent.parent / "model_budget.py",
        runner.SRC.parent / "measurement-audit.mjs",
        *[path for path in (root / "workspace").rglob("*") if path.is_file()],
        *(root / "skills").rglob("SKILL.md")]
    runner.write(runner.PAIR / "manifest.json", dict(source_sha256={str(path): runner.sha(path) for path in pins}))
    runner.write(runner.PAIR / "dispatch.json", dict(task_id=release["task_id"], release_sha256=runner.sha(RELEASE),
        public_sha256=release["public_sha256"], public_files=["TASK.md", "settings.json"],
        maintenance_fixture_or_reference_dispatched=False, starting_case_empty=True))


if __name__ == "__main__":
    {"freeze": freeze, "prepare": prepare, "agent": runner.agent, "operator": runner.operator}[sys.argv[1]]()
