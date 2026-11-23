"""Run the three incomplete dimensionless signal-readout development pairs in new paths."""
import argparse
import shutil
import sys
import hashlib
import zipfile
from local_first_wave import (HERE, base, batch, common_environment, dispatch, files, launch_attempt,
                              read, runtime, runtime_digest, sha, snapshot_runtime, write)

OUT = base/"readout_pairs_20261120"
TASKS = ("B14","B17","B21")
ARMS = ("general","professional")


def prepare():
    OUT.mkdir(exist_ok=False)
    pins = {str(p):sha(p) for p in [HERE/"readout_pair_retest.py",HERE/"readout_delivery/SKILL.md",
            HERE/"pressure-tool.mjs", HERE.parent/"launch_attempt.py",HERE.parent/"native_attempt.mjs",
            HERE.parent/"model_budget.py",runtime/"snapshot.json",
            base.parents[2]/"graduation-thesis-materials/graduation-research/benchmarks/chapter03.md"]}
    for short in TASKS:
        task = "CH3-DEV-"+short
        pair = OUT/task
        entry = next(r for r in read(dispatch/"index.json") if r["id"] == task)
        package = dispatch/entry["zip"]
        if sha(package) != entry["sha256"]:
            raise ValueError("public ZIP hash mismatch")
        with zipfile.ZipFile(package) as z:
            expected = {n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith("/")}
        sources = dict(pins)
        for arm in ARMS:
            root = pair/arm
            old = base/"B11_dispatch_review_20261118/live"/arm
            public = batch/"work"/arm/task/"first/input"
            if files(public) != expected:
                raise ValueError("changed public package")
            shutil.copytree(public,root/"workspace")
            for directory in ["workspace/common","workspace/delivery","home","tmp","user","cache","agents_home"]:
                (root/directory).mkdir()
            shutil.copytree(old/"skills",root/"skills")
            if arm == "professional":
                shutil.copytree(HERE/"readout_delivery",root/"skills/readout-delivery")
            (root/"dump.yml").write_text((old/"dump.yml").read_text(encoding="utf8").replace(str(old),str(root)),encoding="utf8")
            (root/"prompt.txt").write_text("完成本题 TASK.md，在 delivery/ 交付。仅用本题公开材料和本臂工具。",encoding="utf8")
            for p in [root/"prompt.txt",root/"dump.yml",*(root/"skills").rglob("SKILL.md")]:
                sources[str(p)] = sha(p)
        write(pair/"manifest.json",dict(task=task,role="selective_development_retest",public_sha256=sha(package),
                                         source_sha256=sources,max_requests=100,cluster_jobs=0))


def run(short,arm):
    pair = OUT/("CH3-DEV-"+short)
    root = pair/arm
    binding = read(base/"pilot_decision_20261117"/(arm+".binding.json"))
    binding.pop("cluster",None)
    grant = dict(live_model_allowed=True,arms=[arm],pair_manifest_sha256=sha(pair/"manifest.json"),
        authorization_evidence="2026-11-20 user-directed separate development retests",
        isolation_accepted=True,isolation_evidence="distinct per-arm workspaces, shared host",
        budget_unit="requests",max_requests_per_arm=100,max_output_tokens=8192,wall_seconds=14400,
        generation=binding["generation"],**{k:binding[k] for k in ("model","context_window","endpoint_sha256")})
    snapshot_runtime.sha = runtime_digest
    launch_attempt.common_environment = lambda r: dict(common_environment(r), C3_PYTHON=sys.executable,
        C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime))
    code = launch_attempt.run(pair,arm,binding,grant)
    from local_recheck_100 import seal_arm
    seal_arm(root,root,short,arm,code)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action",choices=["prepare","run"])
    args = p.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        for i,short in enumerate(TASKS):
            for arm in (ARMS if i % 2 == 0 else reversed(ARMS)):
                root = OUT/("CH3-DEV-"+short)/arm
                if (root/"sealed.json").exists():
                    if read(root/"sealed.json")["archive_sha256"] != sha(root/"submission.zip"):
                        raise ValueError("sealed ZIP changed")
                    continue
                run(short,arm)
