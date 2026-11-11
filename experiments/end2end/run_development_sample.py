"""Chapter 3 public-input DSH development run; no accuracy scoring or key fallback."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parents[2]
WORKSPACE = PROJECT.parent
BASE = WORKSPACE.parent
SAMPLE = WORKSPACE / "graduation-datasets/chapter03_simulation_tasks/benchmark/development_samples/b01_2_e2e_20261102"
ARCHIVE = WORKSPACE / "graduation-experiment-results/chapter3_end_to_end_evaluation/development_samples/b01_2_dsh"
SECRET = PROJECT / "config/llm/chapter3/.env.private"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def configuration(path=SECRET, required=True):
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    if required and any(not values.get(k) for k in ("CHAPTER3_BASE_URL", "CHAPTER3_MODEL", "CHAPTER3_API_KEY")):
        raise ValueError("Missing Chapter 3 endpoint/model/independent key; no Chapter 2 or process-key fallback is allowed")
    return values


def environment(cfg, run):
    env = {k: v for k, v in os.environ.items()
           if not re.search(r"KEY|TOKEN|SECRET|PASSWORD|AUTH", k, re.I)
           and not k.startswith(("DEEPSEEK_", "OPENAI_", "XCM_", "QWEN_"))}
    env.update({"PRINCIPIA_CHAPTER3_API_KEY": cfg.get("CHAPTER3_API_KEY", ""),
                "DSH_HOME": str(run / "runtime/home"), "DSH_TELEMETRY_MODE": "DISABLED",
                "PRINCIPIA_PROJECT_ROOT": str(PROJECT), "PRINCIPIA_PYTHON": str(PROJECT / ".venv/Scripts/python.exe"),
                "PRINCIPIA_CASE_ROOT": str(run / "alias"), "ENABLE_EXECUTION": "false", "REQUIRE_EXECUTION": "false",
                "RETRIEVAL_LLM_API_KEY": "", "PYTHONUTF8": "1", "DSH_PERMISSION_MODE": "danger-full-access"})
    return env


def prepare(run, cfg, host, remote, code):
    # Reuse the installed application and SSH plugin, with a fresh, credential-free DSH home.
    profile = run / "runtime/home/profiles/headless"
    profile.mkdir(parents=True, exist_ok=True)
    modules = profile / "node_modules"
    existing = BASE / "dsh-home/chapter3/profiles/web-ssh/node_modules"
    if not modules.exists():
        junction_env = {**os.environ, "C3_JUNCTION_PATH": str(modules), "C3_JUNCTION_TARGET": str(existing)}
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "New-Item -ItemType Junction -Path $env:C3_JUNCTION_PATH -Target $env:C3_JUNCTION_TARGET | Out-Null"],
                       env=junction_env, check=True, capture_output=True)
    write(profile / "package.json", {"name": "chapter3-development-headless", "private": True,
          "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless",
                                            "principia-blastfoam-dsh-bundle", "dsh-remote-ssh"], "patchReload": "startup"}}})
    (profile / "cordis.patch.yml").write_text("[]\n", encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("readonly_directory.mjs"), profile / "readonly_directory.mjs")
    alias = run / "alias"
    alias.mkdir(exist_ok=True)
    inputs = run / "public_input"
    if not inputs.exists():
        shutil.copytree(SAMPLE / "public", inputs)
    operator_tools = run / "operator_tools"
    operator_tools.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("guarded_remote_job.py"), operator_tools / "guarded_remote_job.py")
    guidance = run / "application_skills"
    guidance.mkdir(exist_ok=True)
    for skill in [PROJECT / ".dsh/skills/blastfoam-workflow/SKILL.md"]:
        target = guidance / skill.parent.name / "SKILL.md"
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(skill, target)
    model = cfg.get("CHAPTER3_MODEL") or "pending-model"
    patch = [
        {"insert": [{"id": "principia-readonly-directory", "name": (profile / "readonly_directory.mjs").as_uri(), "config": {"workspace": remote}}]},
        {"id": "llm-deepseek", "disabled": True},
        {"id": "llm-pi-ai", "config": {"providers": {"chapter3-xcm": {
            "api": cfg.get("CHAPTER3_API", "openai-completions"),
            "apiKeyEnv": "PRINCIPIA_CHAPTER3_API_KEY", "baseURL": cfg.get("CHAPTER3_BASE_URL") or "https://xcmapi.org/v1",
            "models": [{"id": model, "contextWindow": int(cfg.get("CHAPTER3_CONTEXT_WINDOW") or 32768),
                        "maxTokens": int(cfg.get("CHAPTER3_MAX_OUTPUT_TOKENS") or 4096), "input": ["text"]}],
            "compat": {"thinkingFormat": "deepseek"}, "timeoutMs": 180000,
            "retryPolicy": {"mode": "normal", "maxRetries": 1}}}}},
        {"id": "agent-default-model", "config": {"provider": "chapter3-xcm", "model": model}},
        {"id": "remote-ssh-manager", "config": {"aliasRoot": str(run / "aliases"),
            "servers": [{"id": "development", "sshTarget": host, "label": host, "remoteCodeCommand": code,
                         "sshArgs": ["-o", "BatchMode=yes"]}],
            "workspaces": [{"id": "development", "serverId": "development", "remotePath": remote, "aliasPath": str(alias)},
                {"id": "installed-blastfoam", "serverId": "development", "remotePath": "/data/OpenFOAM/blastfoam", "aliasPath": str(run / "installation_alias/blastfoam")},
                {"id": "installed-openfoam", "serverId": "development", "remotePath": "/data/OpenFOAM/OpenFOAM-9", "aliasPath": str(run / "installation_alias/openfoam")}]}},
        {"id": "remote-ssh-web", "disabled": True},
        {"id": "remote-ssh-directory-browser", "disabled": True},
        {"id": "principia-retrieval-mcp", "disabled": True},
        # Explicit bundled root is host-local even when ctx.fs routes to SSH.
        # No application skill is copied to the remote machine.
        {"id": "skill-filesystem", "config": {"includeDefaultRoots": False,
            "bundledSkillDir": str(guidance), "watch": False}},
    ]
    # Keep the existing DSH application roles. Remote execution uses native SSH-routed
    # tools, not the Windows-only MCP case/execution tools. Config rows replace wholesale.
    import yaml
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node))
    rows = yaml.load((PROJECT / "packages/principia-dsh-bundle/cordis.patch.yml").read_text(encoding="utf-8"), Loader=Loader)
    for group in rows:
        for row in group.get("insert", []):
            if row["id"] in {"principia-physics-analyst", "principia-case-setup", "principia-execution-specialist", "principia-postprocessor", "principia-reviewer"}:
                config = row["config"]
                # This headless runtime exposes search via bash, not standalone
                # glob/grep tools; tools.restrict rejects unknown names outright.
                allowed = [x for x in config["toolFilter"]["allow"]
                           if not x.startswith("mcp__") and x not in {"glob", "grep"}]
                if row["id"] in {"principia-case-setup", "principia-execution-specialist", "principia-postprocessor"}:
                    allowed += ["bash", "write", "edit"]
                config["toolFilter"]["allow"] = sorted(set(allowed))
                config["toolFilter"]["allow"].append("principia_list_directory")
                config["persona"] += " This development task uses only supplied public inputs; no tutorial or MCP is required. Use native SSH-routed filesystem/shell tools. Never repair or modify solver installations."
                config["persona"] += " Cite the supplied public files as task evidence. Tutorial selection and model re-derivation are not required. Discover real installed paths with principia_list_directory instead of guessing paths."
                patch.append({"id": row["id"], "config": config})
    (run / "runtime/development.patch.yml").write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = f"""Execute the Chapter 3 end-to-end DEVELOPMENT task in this Remote SSH workspace: {remote}
Read public/request.md, public/conditions.json and public/deliverables.md. Start with an empty submission/case.
Only the supplied public inputs, installed program documentation, and a fresh case are task materials.
Do not read other benchmark/reference/result directories on the host. Do not copy a tutorial or historical case.
First load the project skill blastfoam-workflow, then use its ordered specialist phases. Native tools run remotely.
The application workflow skill is loaded by the local DSH skill provider. It is system guidance, not a reference answer.
The task-provided conditions and fixed materials are the authoritative inputs; this development task does not ask you to re-derive or audit solver implementation or material calibration.
Use the supplied field list and configuration specifications to build the case. Consult installed documentation only as needed for syntax; avoid an open-ended source-code investigation.
Use principia_list_directory for read-only path discovery. For fixed task inputs, public files are sufficient evidence; tutorial selection and re-deriving the prescribed model are not required.
Local Principia MCP is disabled because this task runs on Linux through SSH. Keep all work in this workspace.
The operator-provided fixed model/numerical dictionaries may be copied. Construct the remaining case and source initialisation yourself.
Use /data/miniconda3/bin/python3. For OpenFOAM shells first source /data/OpenFOAM/OpenFOAM-9/etc/bashrc and /data/OpenFOAM/blastfoam/etc/bashrc.
Run one end-to-end attempt, from meshing through blastFoam to postprocessing and deliverables in submission/.
Single CPU, cumulative simulation process wall budget 5400s, 3GiB memory; preserve failed commands and raw logs.
Before any solver process, apply one-CPU affinity, 3GiB memory cap, timeout, and check 2GiB minimum free space.
Meshing and physical-field initialisation are simulation work too: use the same guard and workspace budget with distinct setup job names (setup_01, setup_02, etc.). Poll each job to completion before its dependent job. Do not give setup and production separate 5400s allowances.
For production execution use the supplied application guard, not a foreground solver pipeline or a self-written runner.
After sourcing both bashrc files, run this SHORT launch command, then poll its status using separate short tool calls:
/data/miniconda3/bin/python3 operator_tools/guarded_remote_job.py start --workspace {remote} --cwd {remote}/submission/case --job {remote}/execution_jobs/production_01 --timeout-seconds 5400 --budget-seconds 5400 -- blastFoam -case {remote}/submission/case
Poll /data/miniconda3/bin/python3 operator_tools/guarded_remote_job.py status --job {remote}/execution_jobs/production_01.
The guard enforces one CPU and inherited per-process 3GiB address-space limits, and monitors cumulative wall time, storage/free-space and raw solver logs. This is a serial solver process bound, not an aggregate cgroup RSS claim.
The guard's process.log and status.json are original execution evidence; preserve them in the delivery along with scripts. A status of process_completed is only process evidence, not full task acceptance.
On model_anomaly_stop stop the workflow, deliver an honest failure report and evidence manifest, and do not restart. Postprocessing may be marked unavailable; never fabricate a complete pressure window.
If a remote tool client shuts down, do not infer that its detached process stopped. Keep the job identity; reconnect and read the same status or report it unknown. Never launch a replacement job merely because a tool disconnected.
If known model behavior produces invalid fields, negative/zero mixture T, nonfinite states, or a solver failure, stop that run and preserve evidence.
Do not repair a solver, change EOS/activation/flux/temperature floor, replace material, tune physics, or conceal failures.
Only assess condition implementation, completion and delivery. Accuracy is NOT scored. Old reference outputs are not available.
Keep all requested submission files and scripts, plus standard workflow reports where applicable. Mark unavailable artifacts honestly.
Record real commands and versions; do not claim execution from a generated script alone. Do not contact any model endpoint yourself.
End with PRINCIPIA_DEVELOPMENT_COMPLETE and a factual completed/failed/blocked status.
"""
    (run / "prompt.txt").write_text(prompt, encoding="utf-8")
    write(run / "run_manifest.json", {"sample_id": "C3-DEV-FF-001", "source_sample": str(SAMPLE),
          "remote_host": host, "remote_workspace": remote, "model": model, "provider": "chapter3-xcm",
          "base_url": cfg.get("CHAPTER3_BASE_URL"), "credentials": "Chapter 3 dedicated file only; no fallback; not copied to remote/profile",
          "accuracy_scoring": False, "solver_repair_allowed": False, "dsh_started": False,
          "input_files": [{"path": p.relative_to(inputs).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in inputs.rglob("*") if p.is_file()],
          "application_guidance": [{"path": p.relative_to(guidance).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                   for p in guidance.rglob("SKILL.md")],
          "application_tools": [{"path": "operator_tools/" + p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                for p in operator_tools.iterdir() if p.is_file()]})


def remote_command(host, command, timeout=40):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "-o", "ClearAllForwardings=yes", host, command],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def stage(run, host, remote):
    # Absolute, unique run path; never overwrite a pre-existing remote workspace.
    command = "test ! -e " + shlex.quote(remote) + " && mkdir -p " + shlex.quote(remote + "/public") + " " + shlex.quote(remote + "/operator_tools")
    p = remote_command(host, command)
    if p.returncode:
        raise RuntimeError("Remote stage refused (existing path or SSH failure)")
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes", "-r", str(run / "public_input") + "/.", host + ":" + remote + "/public/"], check=True, capture_output=True)
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes", str(run / "operator_tools/guarded_remote_job.py"), host + ":" + remote + "/operator_tools/"], check=True, capture_output=True)
    write(run / "stage_receipt.json", {"remote_workspace": remote, "task_public_inputs_only": True,
          "application_tools": ["operator_tools/guarded_remote_job.py"], "staged": True})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "dump-config", "run", "collect"])
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--host", default="yan_yun_agent")
    parser.add_argument("--remote-root", default="/home/agent/principia/chapter3-development")
    parser.add_argument("--remote-code", default="/home/agent/.dsh-remote-ssh/bin/code-with-env")
    parser.add_argument("--timeout", type=int, default=10800)
    args = parser.parse_args(argv)
    run = (args.run_dir or ARCHIVE / datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")).resolve()
    run.mkdir(parents=True, exist_ok=True)
    remote = args.remote_root.rstrip("/") + "/" + run.name
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", remote) or ".." in remote.split("/"):
        raise ValueError("Invalid remote workspace")
    cfg = configuration(required=args.action == "run")
    if args.action != "collect":
        prepare(run, cfg, args.host, remote, args.remote_code)
    if args.action == "prepare":
        print(run)
        return 0
    entry = BASE / "deepseek-harness/apps/cli/lib/bin.js"
    command = ["node", str(entry), "--profile", "headless", "--patch", str(run / "runtime/development.patch.yml")]
    env = environment(cfg, run)
    key = cfg.get("CHAPTER3_API_KEY", "")
    if args.action == "dump-config":
        p = subprocess.run([*command, "--dump-config"], cwd=run / "alias", env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        output = p.stdout + p.stderr
        if key:
            output = output.replace(key, "<redacted>")
        (run / "dump-config.txt").write_text(output, encoding="utf-8")
        print(json.dumps({"run_dir": str(run), "exit_code": p.returncode}))
        return p.returncode
    if args.action == "run":
        if (run / "execution.json").exists():
            raise ValueError("One attempt per directory; use a fresh run directory")
        stage(run, args.host, remote)
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["dsh_started"] = True
        write(run / "run_manifest.json", manifest)
        write(run / "execution.json", {"status": "running", "dsh_started": True, "accuracy_scoring": False})
        spec = importlib.util.spec_from_file_location("old_adapter", Path(__file__).with_name("run_agent_benchmark.py"))
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        result = adapter.run_command([*command, (run / "prompt.txt").read_text(encoding="utf-8")], cwd=run / "alias", environment=env, timeout_seconds=args.timeout, log_path=run / "dsh.log")
        # Redact known credential if a transport exception happened to echo it.
        log = run / "dsh.log"
        if key and log.exists():
            log.write_text(log.read_text(encoding="utf-8", errors="replace").replace(key, "<redacted>"), encoding="utf-8")
        result.update({"dsh_started": True, "accuracy_scoring": False, "solver_repair_allowed": False})
        write(run / "execution.json", result)
        print(json.dumps({"run_dir": str(run), "exit_code": result["exit_code"], "timed_out": result["timed_out"]}))
        return result["exit_code"] or 0
    if args.action == "collect":
        tar = remote + "-result.tar.gz"
        p = remote_command(args.host, "tar -czf " + shlex.quote(tar) + " -C " + shlex.quote(remote) + " .", timeout=180)
        if p.returncode:
            raise RuntimeError("Remote evidence archive failed")
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes", args.host + ":" + tar, str(run / "remote-result.tar.gz")], check=True, capture_output=True)
        destination = run / "remote_result"
        destination.mkdir(exist_ok=False)
        with tarfile.open(run / "remote-result.tar.gz") as archive:
            archive.extractall(destination, filter="data")
        contract = json.loads((SAMPLE.parents[1] / "references/contracts/B01-2.yaml").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("development_checker", Path(__file__).with_name("check_development_delivery.py"))
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        queries = [{"file": x["file"], "entry": x["entry"]} for x in checker.development_assertions(contract)]
        script = """import json,subprocess,shlex
queries=QUERIES
case=CASE
output={}
for q in queries:
 command='. /data/OpenFOAM/OpenFOAM-9/etc/bashrc >/dev/null 2>&1; . /data/OpenFOAM/blastfoam/etc/bashrc >/dev/null 2>&1; foamDictionary -noFunctionObjects -entry '+shlex.quote(q['entry'])+' -value '+shlex.quote(case+'/'+q['file'])
 p=subprocess.run(['bash','-lc',command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
 output[q['file']+':'+q['entry']]={'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
print(json.dumps(output))
""".replace("QUERIES", repr(queries)).replace("CASE", repr(remote + "/submission/case"))
        p = remote_command(args.host, "/data/miniconda3/bin/python3 -c " + shlex.quote(script), timeout=180)
        if p.returncode == 0:
            write(run / "operator_dictionary_entries.json", json.loads(p.stdout))
        write(run / "collection.json", {"sha256": hashlib.sha256((run / "remote-result.tar.gz").read_bytes()).hexdigest(), "extracted": True, "remote_retained": True})
        print(run / "remote_result")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
