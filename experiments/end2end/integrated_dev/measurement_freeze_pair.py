"""Freeze package bindings and matched profile conditions without authorizing provider use."""
from measurement_paired_control import OUT, PRIOR, DIAGNOSTIC, HERE, TEMPLATE, runtime, sha, read, write, wave
from pathlib import Path
import subprocess
import sys
import zipfile

annular=DIAGNOSTIC.parent/"annular_diagnostic_20261122"
tasks=[]
for dataset in (annular,DIAGNOSTIC):
    ready=read(dataset/"READY.json")
    for n,h in ready["judge_sha256"].items():
        assert sha(dataset/n)==h
    for item in ready["tasks"]:
        dest=OUT/"public_inputs"/item["id"]
        if not dest.exists():
            subprocess.run([sys.executable,"-B",str(dataset/"pack.py"),"dispatch",item["id"],str(dest)],check=True)
        archive=dataset/item["archive"]
        assert sha(archive)==item["sha256"]
        with zipfile.ZipFile(archive) as z:
            assert sorted(z.namelist())==sorted(p.name for p in dest.iterdir())
            assert all(z.read(n)==(dest/n).read_bytes() for n in z.namelist())
        tasks.append(dict(id=item["id"],cohort=dataset.name,ready_sha256=sha(dataset/"READY.json"),package_sha256=sha(archive),
                          files={p.name:sha(p) for p in dest.iterdir()},judge=ready["judge_sha256"],
                          exposure=item["exposure"],versions_in_order=["old","revised"] if len(tasks)%2==0 else ["revised","old"]))
prior=[]
for r in read(PRIOR/"index.json")["live"]:
    folder=PRIOR/"live"/r["item"]["id"]/"professional"
    grant=read(folder/"attempt_intent.json")["authorization"]
    cap=grant["max_requests_per_arm"]
    assert grant["pair_manifest_sha256"]==sha(folder.parent/"manifest.json")
    prior.append(dict(task=r["item"]["id"],grant_manifest=grant["pair_manifest_sha256"],cap=cap,used=read(folder/"sealed.json")["requests"]))
prompt=PRIOR/"live/C3X15/professional/prompt.txt"
(OUT/"prompt.txt").write_bytes(prompt.read_bytes())
sources=[HERE/"measurement_paired_control.py",HERE/"measurement_shell_reference.py",HERE/"measurement_shell_comparison.py",
         Path(__file__),HERE/"measurement_profile.py",HERE/"measurement-review/SKILL.md",HERE/"measurement-audit.mjs",
         HERE/"driver.mjs",HERE/"pressure-tool.mjs",HERE.parent/"native_attempt.mjs",HERE.parent/"launch_attempt.py",HERE.parent/"model_budget.py",
         runtime/"snapshot.json",runtime.parent/"node_identity.json",TEMPLATE/"dump.yml",*(TEMPLATE/"skills").rglob("SKILL.md")]
protocol=dict(status="frozen_before_new_model_requests",same_question_conditions=dict(
    tasks=tasks,common_prompt_sha256=sha(prompt),model=grant["model"],context_window=grant["context_window"],
    endpoint_sha256=grant["endpoint_sha256"],generation=grant["generation"],max_output_tokens=8192,
    per_session_requests=100,wall_seconds=14400,cluster_jobs=0,model_concurrency=1,
    isolation="distinct new workspace and session per version, same frozen runtime, common public inputs only",
    revisions="old frozen professional config and skills vs identical plus measurement-audit plugin and measurement-review skill",
    scoring="one first attempt per version; seal report before grade; no automatic retry or continuation; missing report fails; record infrastructure reason separately",
    reporting="paired field transitions for terms/amount/decision/evidence, by family, exposure and version; requests, reported tokens, unknown usage and billing",
    sources={str(p):sha(p) for p in sources}),budget=dict(existing_grants=prior,
    new_pair_authorization="no transferable balance evidenced",new_provider_requests=0,new_cluster_jobs=0,
    primary_annular_sessions=4,primary_max_requests=400,additional_diagnostic_sessions=8,additional_max_requests=800,
    full_request_ceiling=1200,money=None))
write(OUT/"protocol.json",protocol)

