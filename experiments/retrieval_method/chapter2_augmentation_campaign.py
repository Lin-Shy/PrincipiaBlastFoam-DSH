"""持久运行第2章开发→正式→评分→报告；各阶段独立进程，不设费用门槛。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from chapter2_augmentation import load, sha, verify


def status(root, value):
    target = root / "RUN_STATUS.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps({**value, "updated_unix": time.time()}, ensure_ascii=False, indent=2) + "\n")
    temp.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if Path(__file__).resolve() != root / "runtime" / Path(__file__).name:
        raise ValueError("execute archived campaign snapshot")
    protocol = verify(root)
    control = root / "control"
    control.mkdir(exist_ok=True)
    with (control / "campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        common = ["--root", str(root)]
        settings = ["--settings-file", str(root / "local_private/.env.qwen_proxy")]
        runner, evaluator = [str(root / "runtime" / name) for name in
                              ("chapter2_augmentation.py", "chapter2_augmentation_evaluation.py")]
        question = load(protocol["inputs"]["dev_questions"]["path"])[0]["id"]
        stages = [("dev_contract", runner, ["run", *common, "--split", "dev", "--arm", "grep",
                   "--question-id", question, "--repeat", "1", *settings])]
        for split in ("dev", "test"):
            stages.extend([(f"{split}_answers", runner, ["launch", *common, "--split", split, *settings]),
                           (f"{split}_mechanism", runner, ["mechanism", *common, "--split", split, *settings]),
                           (f"{split}_score", evaluator, ["score", *common, "--split", split, *settings])])
            if split == "test":
                stages.append(("test_regrade", evaluator, ["regrade", *common, "--split", split, *settings]))
            for command in ("report", "mechanism-report"):
                output = root / "reports" / f"{split}-{command}.json"
                stages.append((f"{split}_{command}", evaluator,
                               [command, *common, "--split", split, "--output", str(output)]))
        completed = []
        for name, program, arguments in stages:
            marker = control / (name + ".complete.json")
            if marker.exists():
                if load(marker)["protocol_sha256"] != sha(root / "protocol.json"):
                    raise ValueError("campaign checkpoint protocol drift")
                completed.append(name)
                continue
            state = {"state": "running", "phase": name, "pid": os.getpid(), "completed": completed,
                     "protocol_sha256": sha(root / "protocol.json"), "resource_limits": protocol["limits"]}
            status(root, state)
            with (control / (name + ".log")).open("a") as log:
                process = subprocess.Popen([sys.executable, program, *arguments], stdout=log, stderr=subprocess.STDOUT,
                                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
                status(root, {**state, "child_pid": process.pid})
                returncode = process.wait()
            if returncode:
                status(root, {**state, "state": "failed", "returncode": returncode,
                              "log": str((control / (name + ".log")).relative_to(root))})
                raise RuntimeError("campaign phase failed; preserve artifacts and resume after correction")
            if name == "dev_contract":
                session = load(root / "runs/dev" / question / "r1/grep/session.json")
                if not any(not e.get("error") for e in session["tools"]):
                    status(root, {**state, "state": "failed", "reason": "development contract did not execute a valid tool; stop before bulk runs"})
                    raise RuntimeError("agent tool interface contract failed")
            marker.write_text(json.dumps({"protocol_sha256": sha(root / "protocol.json"), "finished_unix": time.time()}) + "\n")
            completed.append(name)
        status(root, {"state": "complete", "phase": "finished", "pid": os.getpid(), "completed": completed,
                      "protocol_sha256": sha(root / "protocol.json")})


if __name__ == "__main__":
    main()
