"""正式网格进程编排；最多三并发，生产与评分进程隔离，不创建智能体。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
from pathlib import Path
import random
import subprocess
import sys
import time

from chapter2_formal_runtime import verify, save, ANSWER_ARMS, SELF_ARMS, BASE_ARMS


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--settings-file", type=Path, required=True)
    args = p.parse_args()
    root = args.root.resolve()
    protocol, protocol_sha = verify(root)
    locks = root / "locks"
    locks.mkdir(exist_ok=True)
    with (locks / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempt = root / "controller_attempts" / str(time.time_ns())
        attempt.mkdir(parents=True)
        def worker(stage, arm=None, shard=None):
            script = "chapter2_formal_review.py" if stage in {"prepare", "run", "adjudicate"} else "chapter2_formal_runtime.py"
            cmd = [sys.executable, str(root / "runtime" / script), stage, "--root", str(root)]
            if stage != "native":
                cmd += ["--settings-file", str(args.settings_file.resolve())]
            if arm:
                cmd += ["--arm", arm]
            if shard is not None:
                cmd += ["--shard", str(shard)]
            label = stage + "--" + (arm or (str(shard) if shard is not None else "shared"))
            begin = time.monotonic()
            with (attempt / (label + ".log")).open("x") as output:
                result = subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT)
            save(attempt / (label + ".json"), {"stage": stage, "arm": arm, "shard": shard,
                "exit_code": result.returncode, "seconds": time.monotonic()-begin, "protocol_sha256": protocol_sha})
            print("STAGE", label, "exit", result.returncode, flush=True)
            if result.returncode:
                raise RuntimeError("frozen worker stopped; inspect retained stage log: " + label)
        rng = random.Random(protocol["seed"])
        worker("planner")
        native = list(SELF_ARMS) + list(BASE_ARMS)
        rng.shuffle(native)
        with ThreadPoolExecutor(max_workers=protocol["recovery"]["concurrency"]) as pool:
            list(pool.map(lambda arm: worker("native", arm), native))
        arms = list(ANSWER_ARMS)
        rng.shuffle(arms)
        with ThreadPoolExecutor(max_workers=protocol["recovery"]["concurrency"]) as pool:
            list(pool.map(lambda arm: worker("answer", arm), arms))
        if not (root / "completion/review_prepare.json").exists():
            worker("prepare")
        for stage in ("run", "adjudicate"):
            with ThreadPoolExecutor(max_workers=protocol["recovery"]["concurrency"]) as pool:
                list(pool.map(lambda shard: worker(stage, shard=shard), range(protocol["scoring_shards"])))
        completion = root / "completion" / "controller.json"
        if not completion.exists():
            save(completion, {"status": "complete", "protocol_sha256": protocol_sha,
                "remaining": "zero-model source/replay/statistics plus real-human sample and chapter2 Office delivery"})


if __name__ == "__main__":
    main()
