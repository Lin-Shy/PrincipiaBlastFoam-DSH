"""使用历史冻结源码补齐零模型重放；所有新写入重定向到派生归档。"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()
    run, output = args.run.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(run))
    runner = importlib.import_module("runner")
    qa, graphify = runner.qa, runner.graphify
    protocol = runner.audit.verify(run)
    graphify.verify_runtime(protocol)
    original_write = qa.write

    def save(path, value):
        path = Path(path).resolve()
        if path.is_relative_to(run):
            path = output / "redirected_writes" / path.relative_to(run)
        original_write(path, value)

    qa.write = save
    graphify.BASE_WRITE = save
    graphify.SECRET = ""

    def forbidden_network(*args, **kwargs):
        raise RuntimeError("network forbidden in historical replay")

    qa.urlopen = graphify.urlopen = forbidden_network
    graphify.install()
    with (output / "runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        questions = {q["id"]: q for q in qa.read(run / "control/questions.json")}
        engines = {}
        jobs, previous = [], []
        result_hashes = {}
        for arm, method in runner.GROUPS.items():
            if arm in ("control", "native", "text_adapter"):
                engines[arm] = graphify.Engine(run / arm, arm)
            elif arm == "principia_index_free":
                engines[arm] = runner.candidate.Engine(run / arm, arm, run / "principia-graph.json", runner.candidate.DEFAULTS)
            else:
                engines[arm] = runner.vector.Engine(run / arm, arm, run / "vector-index", runner.candidate.DEFAULTS)
            for folder in sorted((run / arm / "sessions").iterdir()):
                result = folder / "result.json"
                if not result.is_file():
                    continue
                key = str(folder.relative_to(run))
                result_hashes[key] = sha(result)
                record = qa.read(result)
                successful = [f for f in (folder / "invocations").glob("*.json")
                              if (lambda d: d.get("replay") is True and d.get("status") == record["status"])(qa.read(f))]
                if successful:
                    previous.append({"session": key, "result_sha256": result_hashes[key],
                                     "invocation_sha256": {str(f.relative_to(run)): sha(f) for f in successful}})
                else:
                    jobs.append((arm, questions[record["id"]], method, record["replicate"], key))
        manifest = {"schema": "historical-replay-completion-v1", "protocol_sha256": sha(run / "protocol.json"),
                    "implementation_sha256": sha(Path(__file__)), "prior_success": previous,
                    "result_sha256": result_hashes, "planned_new": len(jobs), "network_calls": 0}
        if (output / "manifest.json").exists():
            raise FileExistsError("choose a new replay output")
        save(output / "manifest.json", manifest)
        state = {"state": "running", "total": len(result_hashes), "prior_success": len(previous),
                 "planned_new": len(jobs), "completed_new": 0, "errors": []}
        save(output / "state.json", state)

        def replay(job):
            arm, question, method, replicate, key = job
            folder = run / key
            if sha(folder / "result.json") != result_hashes[key]:
                raise ValueError("historical result drift")
            call = graphify.run_one if arm in ("control", "native", "text_adapter") else runner.run_with_timing
            begin = time.monotonic()
            result = call(engines[arm], question, method, None, replicate, True)
            if sha(folder / "result.json") != result_hashes[key]:
                raise ValueError("historical result modified")
            save(output / "completed" / (key.replace("/", "--") + ".json"),
                 {"session": key, "status": result["status"], "result_sha256": result_hashes[key],
                  "seconds": time.monotonic() - begin, "network_calls": 0})
            return key

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(replay, job): job[-1] for job in jobs}
            for future in as_completed(pending):
                try:
                    future.result()
                    state["completed_new"] += 1
                except Exception as e:
                    state["errors"].append({"session": pending[future], "type": type(e).__name__, "reason": str(e)[:200]})
                save(output / "state.json", state)
                if (state["completed_new"] + len(state["errors"])) % 25 == 0:
                    print(json.dumps(state), flush=True)
        changed = [key for key, expected in result_hashes.items() if sha(run / key / "result.json") != expected]
        state.update(state="finished", changed_results=changed)
        save(output / "state.json", state)
        print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
