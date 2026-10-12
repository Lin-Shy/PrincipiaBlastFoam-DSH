"""固定开发试点通过后，等待正式问答完成，再重评和导出；不更改原流水线。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--revision", type=Path, required=True)
    p.add_argument("--worker-python", type=Path, required=True)
    p.add_argument("--plot-python", type=Path, required=True)
    p.add_argument("--connection-guard", type=Path)
    args = p.parse_args()
    root, revision = args.root.resolve(), args.revision.resolve()
    script = revision / "runtime/chapter2_atomic_judge.py"
    exporter = revision / "runtime/build_report.py"
    binding = {"pid": os.getpid(), "revision_sha256": sha(revision / "protocol.json"),
               "script_sha256": sha(script), "exporter_sha256": sha(exporter), "supervisor_sha256": sha(Path(__file__))}
    if args.connection_guard:
        binding["connection_guard_sha256"] = sha(args.connection_guard)
        binding["connection_guard_amendment_sha256"] = sha(revision / "connection_guard_amendment_001.json")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    exported = []

    def status(state, phase, **extra):
        target = revision / "SUPERVISOR_STATUS.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps({**binding, "state": state, "phase": phase, "exported": exported,
                                    "updated_unix": time.time(), **extra}, ensure_ascii=False, indent=2) + "\n")
        temp.replace(target)

    with (revision / "supervisor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            while True:
                if (revision / "pilot-summary.json").exists():
                    try:
                        pilot = load(revision / "pilot-summary.json")
                        break
                    except json.JSONDecodeError:
                        pass  # 输出文件已创建但尚未写完。
                launch = revision / "pilot_launch_001.json"
                if launch.exists():
                    pid = load(launch)["pid"]
                    proc = Path("/proc") / str(pid)
                    if not proc.exists() or proc.joinpath("stat").read_text().split(") ", 1)[1].startswith("Z"):
                        raise RuntimeError("pilot exited without a complete summary; see pilot.log")
                status("waiting", "fixed_dev_pilot")
                time.sleep(15)
            if pilot["status"] != "passed" or pilot["revision_sha256"] != binding["revision_sha256"]:
                status("stopped", "fixed_dev_pilot", reason="pilot_failed; no bulk scoring")
                return
            while not (root / "control/test_answers.complete.json").exists():
                parent = load(root / "RUN_STATUS.json")
                status("waiting", "parent_test_answers", parent_phase=parent["phase"],
                       completed_test_answers=len(list((root / "runs/test").rglob("session.json"))))
                if parent["state"] == "failed":
                    raise RuntimeError("parent campaign failed")
                time.sleep(15)
            if sha(revision / "protocol.json") != binding["revision_sha256"] or sha(script) != binding["script_sha256"]:
                raise ValueError("revision binding drift")
            with (revision / "campaign.log").open("a") as log:
                command = [str(args.worker_python.absolute()), str(script), "campaign", "--root", str(root), "--revision", str(revision)]
                if args.connection_guard:
                    command = [str(args.worker_python.absolute()), str(args.connection_guard.absolute()), "--revision", str(revision),
                               "--entry", str(script), "--", "campaign", "--root", str(root), "--revision", str(revision)]
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
                while True:
                    status("running", "revised_scoring_and_export", child_pid=child.pid)
                    for split in ("dev", "test"):
                        if split in exported:
                            continue
                        view = revision / "canonical_view"
                        score_phase = "dev_score" if split == "dev" else "test_regrade"
                        if not (revision / f"{score_phase}.complete.json").is_file() or not (root / "control" / f"{split}_mechanism-report.complete.json").is_file():
                            continue
                        if not all((view / "reports" / f"{split}-{name}.json").is_file() for name in ("report", "mechanism-report")):
                            continue
                        if sha(exporter) != binding["exporter_sha256"]:
                            raise ValueError("exporter drift")
                        destination = revision / "derived/exports_001" / split
                        manifest = destination / "manifest.json"
                        if manifest.exists():
                            if load(manifest)["inputs"].get(str(revision / "protocol.json")) != binding["revision_sha256"]:
                                raise ValueError("existing revised export binding drift")
                        else:
                            with (revision / f"{split}_export.log").open("a") as export_log:
                                result = subprocess.run([str(args.plot_python.absolute()), str(exporter), "--root", str(view),
                                                         "--split", split, "--output", str(destination)],
                                                        stdout=export_log, stderr=subprocess.STDOUT, env=env)
                            if result.returncode:
                                raise RuntimeError("revised report export failed")
                        exported.append(split)
                    code = child.poll()
                    if code is not None:
                        if code:
                            raise RuntimeError("revised scoring failed; see campaign.log")
                        if set(exported) != {"dev", "test"}:
                            raise RuntimeError("revised campaign ended without full exports")
                        break
                    time.sleep(15)
            status("complete", "finished")
        except Exception as exc:
            status("failed", "see_logs", error_type=type(exc).__name__)
            raise


if __name__ == "__main__":
    main()
