"""Operator side of PIPE-01. Upload only fixed code and reserialized numeric data."""
import argparse
import json
import tarfile
import time
import subprocess

from pipe_client import validate
from run_pair import ARMS, PAIR, SOURCE, base, read, sha, write
import cluster_job


def operate(arm, pair=PAIR, run_id=None, accepted_case=None, collect_only=False):
    root = pair/arm
    exchange = root/"workspace/pipe_exchange"
    state = root/"operator"
    config = read(base/"pilot_decision_20261117/acceptance.config.json")
    config.update(tasks=1, memory_mib=1024, wall_minutes=15)
    rid = run_id or "c3-pipe01-"+arm+"-20261120"
    grant = dict(live_actions_allowed=True, actions=["stage","submit","status","collect"], run_ids=[rid],
                 limits={k:config[k] for k in ("tasks","memory_mib","wall_minutes")})
    pins = read(pair/"manifest.json")["source_sha256"]
    if collect_only:
        receipt = read(state/"job_receipt.json")
        if receipt["run_id"] != rid or receipt["remote"] != cluster_job.REMOTE_ROOT+"/"+rid:
            raise ValueError("no matching owned job for collection")
    else:
        for p in (SOURCE/"operate.py", SOURCE/"node_solve.py", SOURCE/"pipe_client.py"):
            if sha(p) != pins[str(p)]:
                raise ValueError("pinned operator source changed")
    request = exchange/"request.json"
    if request.stat().st_size > 65536:
        raise ValueError("oversized case")
    case = accepted_case if accepted_case is not None else read(request)
    validate(case)
    payload = state/"input"
    if not (state/"job_receipt.json").exists():
        if not (state/"stage_receipt.json").exists():
            payload.mkdir(parents=True, exist_ok=False)
            write(payload/"case.json",case)
            (payload/"node_solve.py").write_bytes((SOURCE/"node_solve.py").read_bytes())
            (payload/"run_case.sh").write_bytes(b"set -eu\nexec /usr/bin/python3 -I payload/node_solve.py\n")
            cluster_job.run("stage",config,rid,state,payload,grant)
        cluster_job.run("submit",config,rid,state,grant=grant)
    terminal = None
    for _ in range(180):
        try:
            status = cluster_job.run("status",config,rid,state,grant=grant)
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
            from accounting_status import status as accounting
            archived = accounting(config,rid,read(state/"job_receipt.json"))
            status = dict(source="sacct",scheduler_text=" ".join(k+"="+v for k,v in archived.items()))
        with (state/"status.jsonl").open("a",encoding="utf8") as stream:
            stream.write(json.dumps(status)+"\n")
        fields = dict(item.split("=",1) for item in status["scheduler_text"].split() if "=" in item)
        if fields.get("JobName") != rid:
            raise ValueError("scheduler job identity mismatch")
        if fields["JobState"] not in ("PENDING","CONFIGURING","RUNNING","COMPLETING"):
            terminal = fields
            break
        time.sleep(10)
    if terminal is None:
        raise TimeoutError("job remains pending; reconcile by job ID")
    if (state/"collection_receipt.json").is_file():
        collected = read(state/"collection_receipt.json")
        if sha(state/"collected.tar") != collected["archive_sha256"]:
            raise ValueError("cached collection changed")
    else:
        collected = cluster_job.run("collect",config,rid,state,grant=grant)
    if (root/"sealed.json").exists():
        exchange = state/"post_seal_return"
        exchange.mkdir(exist_ok=True)
    if terminal["JobState"] != "COMPLETED" or terminal["ExitCode"] != "0:0":
        write(exchange/"failure.json",dict(job=collected["job_id"],state=terminal["JobState"]))
        return
    with tarfile.open(state/"collected.tar") as archive:
        def member(name):
            item = archive.getmember("./"+name)
            if not item.isfile() or item.size > 65536:
                raise ValueError("unexpected result member")
            return archive.extractfile(item).read()
        if member("logs/allocated_job_id.txt").decode().strip()!=collected["job_id"] or member("logs/pipeline.exit").strip()!=b"0":
            raise ValueError("node completion mismatch")
        (exchange/"profile.csv").write_bytes(member("profile.csv"))
        receipt = dict(job_id=collected["job_id"], host=member("logs/allocated_host.txt").decode().strip(),
                       scheduler=terminal["JobState"], elapsed=terminal["RunTime"], nodes=terminal["NumNodes"],
                       case_sha256=sha(payload/"case.json"), profile_sha256=sha(exchange/"profile.csv"),
                       archive_sha256=collected["archive_sha256"])
    write(state/"verified.json",receipt)
    write(exchange/"receipt.json",receipt)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("arm",choices=ARMS)
    p.add_argument("--collect-round2",action="store_true")
    args = p.parse_args()
    if args.collect_round2:
        operate(args.arm,pair=base/"pipe_flow_round2_20261120",
                run_id="c3-pipe02-"+args.arm+"-20261120",collect_only=True)
    else:
        operate(args.arm)
