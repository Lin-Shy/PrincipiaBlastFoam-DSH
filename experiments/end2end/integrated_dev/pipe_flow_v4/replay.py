"""Rebuild only from the sealed project; never submit or solve again during grading."""
import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from run import PAIR,read,sha,write


def replay(arm,commands,readme_commands):
    root=PAIR/arm
    target=root/"clean_replay"
    target.mkdir(exist_ok=False)
    review=read(root/"numeric_review.json")
    with zipfile.ZipFile(root/"submission.zip") as archive:
        for name in archive.namelist():
            dest=(target/name).resolve()
            if not dest.is_relative_to(target.resolve()):
                raise ValueError("unsafe archive path")
            if Path(name).name.lower() in {"case.json","summary.json"}:
                continue
            dest.parent.mkdir(exist_ok=True,parents=True)
            dest.write_bytes(archive.read(name))
        original={n:archive.read(n) for n in archive.namelist() if n.split("/")[-1].lower() in {"case.json","summary.json"}}
    logs=[]
    for args in commands:
        process=subprocess.run([sys.executable,*args],cwd=target,capture_output=True,timeout=60)
        logs.append(dict(argv=args,exit=process.returncode,stdout=process.stdout.decode(errors="replace"),stderr=process.stderr.decode(errors="replace")))
    outputs={}
    for name,data in original.items():
        rebuilt=target/name
        outputs[name]=dict(present=rebuilt.is_file(),equal=rebuilt.is_file() and json.loads(rebuilt.read_bytes())==json.loads(data.decode("utf-8-sig")),sha256=sha(rebuilt) if rebuilt.is_file() else None)
    complete=bool(review.get("matrix_matches_node") and review["profile_matches_node"] and review["receipt_matches_node"]
        and review.get("numerical",{}).get("node_field_pass") and review["numerical"].get("summary_pass") and review["readme"] and readme_commands
        and all(row["exit"]==0 for row in logs) and all(any(n.split("/")[-1].lower()==needed and item["equal"] for n,item in outputs.items()) for needed in ("case.json","summary.json")))
    write(root/"replay.json",dict(commands=logs,from_readme=readme_commands,outputs=outputs,full_pass=complete))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("arm")
    parser.add_argument("commands",type=Path)
    args=parser.parse_args()
    spec=read(args.commands)
    replay(args.arm,spec["commands"],spec["from_readme"])
