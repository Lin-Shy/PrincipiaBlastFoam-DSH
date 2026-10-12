"""Run the frozen five-arm development set in fixed, single-worker order."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


ARMS = ("control", "native", "text_adapter", "principia_index_free", "vector_e5_dense")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--settings-file", type=Path, required=True)
    p.add_argument("--upstream", type=Path, required=True)
    a = p.parse_args()
    root = a.run.resolve()
    protocol = json.loads((root / "protocol.json").read_text())
    if protocol["split"] != "dev" or protocol["replicates"] != 1:
        raise ValueError("performance run must use one-repeat development questions")
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = str(a.upstream.resolve())
    record = {"schema": "chapter2-sequential-performance-v1", "run_protocol_sha256": digest(root / "protocol.json"),
              "environment": {"python": sys.version, "platform": platform.platform(),
                              "processor": platform.processor(), "cpu_count": os.cpu_count(),
                              "concurrency": 1, "model": "deepseek-flash"}, "arms": []}
    for arm in ARMS:
        arm_root = root / arm
        existing = list(arm_root.glob("startup-load-*.json"))
        if existing or list((arm_root / "sessions").glob("*/result.json")):
            raise FileExistsError("performance arm already started: " + arm)
        started_ns = time.time_ns()
        command = [sys.executable, str(root / "runner.py"), "run", "--run", str(root),
                   "--only-arm", arm, "--workers", "1", "--settings-file", str(a.settings_file.resolve())]
        with (arm_root / "performance-stdout.log").open("w") as log:
            completed = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        ended_ns = time.time_ns()
        load_files = list(arm_root.glob("startup-load-*.json"))
        if len(load_files) != 1:
            raise ValueError("expected one startup-load record: " + arm)
        ready_ns = int(load_files[0].stem.split("-")[-1])
        if not started_ns < ready_ns < ended_ns:
            raise ValueError("load endpoint outside process interval: " + arm)
        row = {"arm": arm, "started_unix_ns": started_ns, "ready_unix_ns": ready_ns,
               "ended_unix_ns": ended_ns, "startup_to_query_ready_seconds": (ready_ns-started_ns)/1e9,
               "engine_load_seconds": json.loads(load_files[0].read_text())["seconds"],
               "startup_load_record_sha256": digest(load_files[0]),
               "process_exit_code": completed.returncode,
               "completed_results": len(list((arm_root / "sessions").glob("*/result.json"))),
               "stdout_sha256": digest(arm_root / "performance-stdout.log")}
        save(arm_root / "load-measurement.json", row)
        record["arms"].append(row)
        save(root / "sequential-performance.json", record)
        print(json.dumps({"arm": arm, "exit_code": completed.returncode,
                          "completed_results": row["completed_results"]}), flush=True)
        if completed.returncode:
            raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
