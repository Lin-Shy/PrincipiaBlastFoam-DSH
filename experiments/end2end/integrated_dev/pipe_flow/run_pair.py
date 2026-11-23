"""Prepare, run and seal the separate PIPE-01 development pair."""
import argparse
import shutil
import sys
import zipfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE.parent))
from local_first_wave import (HERE, WS, base, common_environment, files, launch_attempt,
                              read, runtime, runtime_digest, sha, snapshot_runtime, write)

PAIR = base / "pipe_flow_20261120"
ARMS = ("general", "professional")


def prepare():
    PAIR.mkdir(exist_ok=False)
    pins = {}
    for path in [*SOURCE.glob("*.py"), SOURCE/"TASK.md", HERE.parent/"native_attempt.mjs",
                 HERE.parent/"launch_attempt.py", HERE.parent/"model_budget.py",
                 HERE.parent/"cluster_job.py", HERE/"pressure-tool.mjs",
                 runtime/"snapshot.json", runtime.parent/"node_identity.json",
                 WS/"graduation-thesis-materials/graduation-research/benchmarks/chapter03.md",
                 WS/"graduation-thesis-materials/graduation-research/chapters/chapter03.md"]:
        pins[str(path)] = sha(path)
    for arm in ARMS:
        root = PAIR / arm
        old = base / "B11_dispatch_review_20261118/live" / arm
        for directory in ["workspace/common", "workspace/delivery", "home", "tmp", "user", "cache", "agents_home"]:
            (root/directory).mkdir(parents=True)
        shutil.copytree(old/"skills", root/"skills")
        (root/"dump.yml").write_text((old/"dump.yml").read_text(encoding="utf8").replace(str(old), str(root)), encoding="utf8")
        for src, dest in [(SOURCE/"TASK.md", root/"workspace/TASK.md"),
                          (SOURCE/"pipe_client.py", root/"workspace/common/pipe_client.py")]:
            shutil.copyfile(src, dest)
        (root/"prompt.txt").write_text("完成 TASK.md 的全部工程，在本次工作区独立交付。节点仅经题面接口使用。", encoding="utf8")
        for p in [root/"dump.yml", root/"prompt.txt", *root.rglob("*.md"), root/"workspace/common/pipe_client.py"]:
            pins[str(p)] = sha(p)
    write(PAIR/"manifest.json", dict(task="PIPE-01", role="separate_development_pair",
          source_sha256=pins, max_requests=100, max_jobs=1, max_node_minutes=15,
          required=["agent_case_generation", "allocated_solve", "raw_velocity", "flow_readout", "reproducible_delivery"]))


def run(arm):
    root = PAIR/arm
    binding = read(base/"pilot_decision_20261117"/(arm+".binding.json"))
    binding.pop("cluster", None)  # The separately operated bridge accepts numeric rows only.
    grant = dict(live_model_allowed=True, arms=[arm], pair_manifest_sha256=sha(PAIR/"manifest.json"),
                 authorization_evidence="2026-11-20 user-directed benign development pair",
                 isolation_accepted=True, isolation_evidence="separate paths on shared development host",
                 budget_unit="requests", max_requests_per_arm=100, max_output_tokens=8192, wall_seconds=14400,
                 generation=binding["generation"], **{k:binding[k] for k in ("model","context_window","endpoint_sha256")})
    snapshot_runtime.sha = runtime_digest
    launch_attempt.common_environment = lambda r: dict(common_environment(r), C3_PYTHON=sys.executable,
        C3_MODULE_PATH=str(HERE.parent), C3_RUNTIME=str(runtime))
    code = launch_attempt.run(PAIR, arm, binding, grant)
    delivery = root/"workspace/delivery"
    with zipfile.ZipFile(root/"submission.zip","x",compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(delivery.rglob("*")):
            if p.is_symlink() or getattr(p.lstat(),"st_file_attributes",0) & 1024:
                raise ValueError("linked submission")
            if p.is_file():
                archive.write(p, p.relative_to(delivery))
    events = read(root/"provider_ledger/ledger.json")["events"]
    write(root/"sealed.json", dict(exit=code, archive_sha256=sha(root/"submission.zip"),
          files=files(delivery), requests=len(events), tokens_reported=sum(e["usage"]["total_tokens"]
          for e in events if e.get("usage")), unsettled=[e["request"] for e in events if not e.get("usage")], money=None))
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", *ARMS])
    action = parser.parse_args().action
    sys.exit(prepare() if action == "prepare" else run(action))
