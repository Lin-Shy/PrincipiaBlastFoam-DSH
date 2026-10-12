"""Run a fixed, small development-question sample with one query at a time."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ARMS = ("control", "native", "text_adapter", "principia_index_free", "vector_e5_dense")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def worker(run, arm, ids, settings, load_only=False):
    sys.path.insert(0, str(run))
    import runner
    import graphify_qa as graphify
    import candidate_qa as candidate
    import vector_retrieval_qa as vector
    import navigation_qa as qa
    from build_natural_navigation_v6 import credential

    protocol = qa.read(run / "protocol.json")
    if protocol["split"] != "dev" or protocol["replicates"] != 1:
        raise ValueError("expected frozen one-repeat development run")
    graphify.verify_runtime(protocol)
    graphify.SECRET = credential(settings)
    graphify.reset_transport_circuit()
    graphify.install()
    start = time.time_ns()
    load_start = time.monotonic()
    if arm in ("control", "native", "text_adapter"):
        engine = graphify.Engine(run / arm, arm)
        fn = graphify.run_one
    elif arm == "principia_index_free":
        engine = candidate.Engine(run / arm, arm, run / "principia-graph.json", candidate.DEFAULTS)
        fn = runner.run_with_timing
    else:
        engine = vector.Engine(run / arm, arm, run / "vector-index", candidate.DEFAULTS)
        fn = runner.run_with_timing
    ready = time.time_ns()
    load = time.monotonic() - load_start
    if load_only:
        write(run / arm / "sampled-load-only-worker.json", {"arm": arm, "query_ready_unix_ns": ready,
              "engine_load_seconds": load})
        return
    questions = {q["id"]: q for q in qa.read(run / "control/questions.json")}
    statuses = []
    for qid in ids:
        if qid not in questions:
            raise ValueError("unknown question: " + qid)
        session = run / arm / "sessions" / f"{qid}--{runner.GROUPS[arm]}--r1"
        if (session / "result.json").exists():
            raise FileExistsError("sample already answered: " + str(session))
        result = fn(engine, questions[qid], runner.GROUPS[arm], graphify.SECRET, 1, False)
        statuses.append({"question_id": qid, "status": result["status"], "result_sha256": sha(session / "result.json")})
        print("DONE", arm, qid, result["status"], flush=True)
    end = time.time_ns()
    write(run / arm / "sampled-load-measurement.json", {
        "arm": arm, "process_start_unix_ns": start, "query_ready_unix_ns": ready,
        "process_end_unix_ns": end, "engine_load_seconds": load,
        "process_start_to_query_ready_seconds": (ready - start) / 1e9,
        "question_ids": ids, "statuses": statuses})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--settings-file", type=Path, required=True)
    p.add_argument("--upstream", type=Path, required=True)
    p.add_argument("--selection", type=Path, required=True)
    p.add_argument("--worker-arm", choices=ARMS)
    p.add_argument("--measure-loads-only", action="store_true")
    p.add_argument("--load-only-worker", action="store_true")
    a = p.parse_args()
    run = a.run.resolve()
    selection = json.loads(a.selection.read_text())
    ids = selection["question_ids"]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("selection must contain distinct questions")
    if a.worker_arm:
        worker(run, a.worker_arm, ids, a.settings_file.resolve(), a.load_only_worker)
        return
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONPATH=str(a.upstream.resolve()))
    if a.measure_loads_only:
        loads = []
        for arm in ARMS:
            command = [sys.executable, str(Path(__file__).resolve()), "--run", str(run),
                       "--settings-file", str(a.settings_file.resolve()), "--upstream", str(a.upstream.resolve()),
                       "--selection", str(a.selection.resolve()), "--worker-arm", arm, "--load-only-worker"]
            started = time.time_ns()
            with (run / arm / "sampled-load-only-stdout.log").open("w") as out:
                completed = subprocess.run(command, env=env, stdout=out, stderr=subprocess.STDOUT)
            if completed.returncode:
                raise RuntimeError("load-only subprocess failed: " + arm)
            obj = json.loads((run / arm / "sampled-load-only-worker.json").read_text())
            loads.append({"arm": arm, "process_start_unix_ns": started,
                          "query_ready_unix_ns": obj["query_ready_unix_ns"],
                          "process_start_to_query_ready_seconds": (obj["query_ready_unix_ns"] - started) / 1e9,
                          "engine_load_seconds": obj["engine_load_seconds"]})
        write(run / "sampled-load-only.json", {"schema": "chapter2-sampled-load-only-v1",
              "selection_sha256": sha(a.selection), "arms": loads})
        print(json.dumps({"loads": len(loads)}))
        return
    record = {"schema": "chapter2-sampled-sequential-performance-v1",
              "selection_sha256": sha(a.selection), "run_protocol_sha256": sha(run / "protocol.json"),
              "concurrency": 1, "question_ids": ids, "arms": []}
    for arm in ARMS:
        if arm == "control":
            sessions = [run / arm / "sessions" / f"{qid}--no_graph--r1" / "result.json" for qid in ids]
            if any(not x.exists() for x in sessions):
                raise ValueError("selected control question missing from interrupted run")
            row = {"arm": arm, "source": "interrupted_full_dev_run", "completed_results": len(sessions),
                   "startup_load_source": sorted((run / arm).glob("startup-load-*.json"))[0].name,
                   "process_start_to_query_ready_seconds": None,
                   "engine_load_seconds": json.loads(sorted((run / arm).glob("startup-load-*.json"))[0].read_text())["seconds"],
                   "process_exit_code": None}
        else:
            command = [sys.executable, str(Path(__file__).resolve()), "--run", str(run),
                       "--settings-file", str(a.settings_file.resolve()), "--upstream", str(a.upstream.resolve()),
                       "--selection", str(a.selection.resolve()), "--worker-arm", arm]
            with (run / arm / "sampled-performance-stdout.log").open("w") as out:
                completed = subprocess.run(command, env=env, stdout=out, stderr=subprocess.STDOUT)
            measured = run / arm / "sampled-load-measurement.json"
            row = {"arm": arm, "source": "sampled_run", "completed_results": 0,
                   "process_exit_code": completed.returncode,
                   "stdout_sha256": sha(run / arm / "sampled-performance-stdout.log")}
            if measured.exists():
                obj = json.loads(measured.read_text())
                row.update({"completed_results": len(obj["statuses"]),
                            "process_start_to_query_ready_seconds": obj["process_start_to_query_ready_seconds"],
                            "engine_load_seconds": obj["engine_load_seconds"],
                            "load_measurement_sha256": sha(measured)})
        record["arms"].append(row)
        write(run / "sampled-performance.json", record)
        print(json.dumps(row), flush=True)
        if row["process_exit_code"] not in (None, 0):
            raise SystemExit(row["process_exit_code"])


if __name__ == "__main__":
    main()
