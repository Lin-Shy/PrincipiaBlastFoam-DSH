"""Recover an ambiguous PIPE-01 submission from the scheduler without resubmission."""
import argparse
import re
import shlex
from operate import operate
from run_pair import ARMS, PAIR, base, read, write
import cluster_job


def recover(arm, pair=PAIR, run_id=None):
    state = pair/arm/"operator"
    intent = read(state/"submit_intent.json")
    rid = run_id or "c3-pipe01-"+arm+"-20261120"
    remote = cluster_job.REMOTE_ROOT+"/"+rid
    if intent["run_id"] != rid or intent["remote"] != remote:
        raise ValueError("unexpected intent")
    config = read(base/"pilot_decision_20261117/acceptance.config.json")
    jobs = cluster_job.ssh(config, "sacct -nXP -S 2026-11-19 --name="+rid+
                           " -o JobID,JobName%64,User,Partition",capture_output=True,text=True)
    candidates = [line.split("|") for line in jobs.stdout.splitlines() if line.strip()]
    if len(candidates) != 1:
        raise ValueError("scheduler history is ambiguous")
    job, name, user, partition = candidates[0][:4]
    if name != rid or not re.fullmatch("[0-9]+",job) or partition != config["partition"]:
        raise ValueError("scheduler accounting identity mismatch")
    details = cluster_job.ssh(config,"scontrol -o show job "+job,capture_output=True,text=True)
    fields = dict(kv.split("=",1) for kv in shlex.split(details.stdout) if "=" in kv)
    if fields.get("JobName") != rid or fields.get("WorkDir") != remote or fields.get("Command") != remote+"/batch.sh" or fields.get("UserId","").split("(")[0] != user:
        raise ValueError("scheduler working directory, command or owner mismatch")
    write(state/"reconciliation.json",dict(job_id=job,job_name=name,work_dir=remote,
          command=fields["Command"],state=fields["JobState"],partition=partition))
    write(state/"job_receipt.json",dict(run_id=rid,remote=remote,job_id=job))
    operate(arm,pair=pair,run_id=rid)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("arm",choices=ARMS)
    recover(p.parse_args().arm)
