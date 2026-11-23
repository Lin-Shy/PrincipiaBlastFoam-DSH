"""Rebuild sealed target tables from clean public inputs and a reviewed README entry."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from check_readout_retest import compare
from readout_pair_retest import ARMS, OUT, TASKS, batch, read, sha, write


def replay(short,arm,entry,args,from_public_root):
    task = "CH3-DEV-"+short
    root = OUT/task/arm
    review = root/"review_replay"
    score = compare(task)[arm]
    changed = [row["file"] for row in score["tables"]["expected_changed.csv"]]
    if not changed:
        raise ValueError("no root target table in sealed ZIP")
    public = batch/"work"/arm/task/"first/input"
    shutil.copytree(public,review)
    delivery = review/"delivery"
    delivery.mkdir()
    with zipfile.ZipFile(root/"submission.zip") as archive:
        for name in archive.namelist():
            target = delivery/name
            if Path(name).is_absolute() or not target.resolve().is_relative_to(delivery.resolve()):
                raise ValueError("unsafe ZIP path")
            if name in changed:
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.read(name))
    cwd = review if from_public_root else delivery
    command = [sys.executable,entry,*args]
    process = subprocess.run(command,cwd=cwd,capture_output=True,timeout=90)
    (review/"replay.stdout").write_bytes(process.stdout)
    (review/"replay.stderr").write_bytes(process.stderr)
    expected = read(root/"sealed.json")["files"]
    rebuilt = {n:sha(delivery/n) if (delivery/n).is_file() else None for n in changed}
    matched = all(rebuilt[n] == expected[n] for n in changed)
    report = dict(task=task,arm=arm,command=[Path(sys.executable).name,entry,*args],
        cwd=cwd.relative_to(review).as_posix(),archive_sha256=score["archive_sha256"],
        exit=process.returncode,rebuilt_hashes=rebuilt,hashes_match=matched,numeric_tables=score["tables"])
    write(root/"review.json",report)
    return process.returncode == 0 and matched


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from-public-root", action="store_true")
    p.add_argument("short",choices=TASKS)
    p.add_argument("arm",choices=ARMS)
    p.add_argument("entry")
    p.add_argument("arguments",nargs=argparse.REMAINDER)
    a = p.parse_args()
    sys.exit(0 if replay(a.short,a.arm,a.entry,a.arguments,a.from_public_root) else 1)
