"""Prepare an inspection-only Chapter 3 profile; never launch an agent or solver.

Copies the application bundle and one explicit skill. Framework dependencies are
still external and hash-bound, so this is NOT a production isolation mechanism.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[2]
WS = PROJECT.parent
ARCHIVE = WS / "graduation-experiment-results/chapter3_end_to_end_evaluation"


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(destination):
    destination = destination.resolve()
    if not destination.is_relative_to(ARCHIVE.resolve()):
        raise ValueError("Offline profile must be inside Chapter 3 archive")
    if destination.exists():
        raise FileExistsError("Refusing to reuse an existing profile directory")
    destination.mkdir(parents=True)
    home = destination / "home"
    profile = home / "profiles/headless"
    package = profile / "node_modules/principia-blastfoam-dsh-bundle"
    package.mkdir(parents=True)
    source = PROJECT / "packages/principia-dsh-bundle"
    files = [source/"package.json", source/"cordis.patch.yml", *sorted((source/"lib").glob("*"))]
    copied = {}
    for file in files:
        if not file.is_file() or file.is_symlink():
            raise ValueError("Unexpected bundle source")
        before = digest(file)
        target = package / file.relative_to(source)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(file,target)
        if digest(target)!=before or digest(file)!=before:
            raise RuntimeError("Bundle changed during snapshot")
        copied[target.relative_to(destination).as_posix()] = before
    skill = PROJECT / ".dsh/skills/blastfoam-workflow/SKILL.md"
    target = destination / "skills/blastfoam-workflow/SKILL.md"
    target.parent.mkdir(parents=True)
    before = digest(skill);shutil.copyfile(skill,target)
    if digest(skill)!=before or digest(target)!=before:
        raise RuntimeError("Skill changed during snapshot")
    copied[target.relative_to(destination).as_posix()] = before
    for name in ["workspace","tmp","cache","agents_home"]:
        (destination/name).mkdir()
    def write(path,value):
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    write(profile/"package.json",{"name":"chapter3-offline-inspection","private":True,
          "dsh":{"profile":{"bundles":["@deepseek-ai/dsh-base","@deepseek-ai/dsh-headless","principia-blastfoam-dsh-bundle"]}}})
    patch=[{"id":"skill-filesystem","config":{"includeDefaultRoots":False,"customSkillDirs":[],
            "bundledSkillDir":str(destination/"skills"),"dshHome":str(home),"agentsHome":str(destination/"agents_home"),"watch":False}}]
    patch += [{"id":name,"disabled":True} for name in ["llm-deepseek","llm-pi-ai","principia-retrieval-mcp","principia-simulation-mcp","principia-simulation-files-mcp","remote-ssh-manager"]]
    write(profile/"cordis.patch.yml",patch)
    upstream=WS.parent/"deepseek-harness"
    external={str(p):digest(p) for p in [upstream/"apps/cli/lib/bin.js",upstream/"pnpm-lock.yaml",upstream/"packages/skill/skill-filesystem/lib/index.js"]}
    env={k:v for k,v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET|PASSWORD|AUTH",k,re.I)
         and not k.startswith(("DSH_","PRINCIPIA_","OPENAI_","DEEPSEEK_"))}
    env.update(DSH_HOME=str(home),DSH_AGENTS_HOME=str(destination/"agents_home"),DSH_TELEMETRY_MODE="DISABLED",
               TMP=str(destination/"tmp"),TEMP=str(destination/"tmp"),XDG_CACHE_HOME=str(destination/"cache"),PYTHONDONTWRITEBYTECODE="1")
    process=subprocess.run(["node",str(upstream/"apps/cli/lib/bin.js"),"--profile","headless","--dump-config"],
                           cwd=destination/"workspace",env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
    (destination/"dump.yml").write_text(process.stdout,encoding="utf-8")
    (destination/"dump.stderr.log").write_text(process.stderr,encoding="utf-8")
    changed=[p for p,h in external.items() if digest(Path(p))!=h]
    manifest={"scope":"static inspection only","real_run_allowed":False,"shared_framework_dependencies_fully_copied":False,
              "copied_sha256":copied,"external_sha256":external,"external_changed_during_dump":changed,
              "dump_exit_code":process.returncode,"source_files_include_scoring_material":False,
              "limitations":["No OS sandbox; same-user arbitrary shell can access other readable paths.",
                             "External hash checks do not isolate mutable dependencies or eliminate TOCTOU.",
                             "No model, SSH, solver, port reservation, budget or global admission permission."]}
    write(destination/"manifest.json",manifest)
    if process.returncode or changed:
        raise RuntimeError("Offline profile inspection failed; evidence retained")
    print(json.dumps({"destination":str(destination),"copied_files":len(copied),"dump_exit_code":process.returncode,"real_run_allowed":False}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination",type=Path)
    prepare(parser.parse_args().destination)
