"""Dispatch the first public package in each as-yet unrepresented task family."""
import argparse
import json
import zipfile
from wave import ARMS,DATA,OUT,SOURCE,read,run,run_pair,sha,write


def prepare():
    ready=read(DATA/"READY.json")
    first=read(OUT/"intake.json")
    if sha(DATA/"READY.json")!=first["ready_sha256"]:
        raise ValueError("release identity changed")
    covered={row["family"] for row in ready["tasks"] if row["id"] in first["selected"]}
    selected=[]
    for row in ready["tasks"]:
        if row["family"] not in covered:
            covered.add(row["family"])
            selected.append(row)
    write(OUT/"intake_families.json",dict(ready_sha256=first["ready_sha256"],
          selector="first in READY for each remaining family",selected=[row["id"] for row in selected],
          requests_per_arm=100,node_jobs=0))
    for row in selected:
        if row["stratum"]=="node-solve":
            raise ValueError("unexpected node family")
        task=row["id"]
        package=DATA/row["archive"]
        if sha(package)!=first["packages"][task]:
            raise ValueError("public ZIP changed")
        pair=OUT/task
        run_pair.PAIR=pair
        run_pair.prepare()
        path=pair/"manifest.json"
        manifest=read(path)
        pins=manifest["source_sha256"]
        for arm in ARMS:
            root=pair/arm
            work=root/"workspace"
            for placeholder in (work/"TASK.md",work/"common/pipe_client.py"):
                pins.pop(str(placeholder),None)
                placeholder.unlink()
            with zipfile.ZipFile(package) as z:
                for n in ("task.json","settings.json","records.json"):
                    (work/n).write_bytes(z.read(n))
            (root/"prompt.txt").write_text("独立完成 task.json，公开输入为 settings.json 和 records.json。将题面要求的 report.json 放入 delivery/。仅使用当前公开包及本臂工具。",encoding="utf8")
            pins[str(root/"prompt.txt")]=sha(root/"prompt.txt")
        for src in (SOURCE/"family_wave.py",SOURCE/"wave.py",package,DATA/"READY.json"):
            pins[str(src)]=sha(src)
        manifest.update(task=task,stratum=row["stratum"],family=row["family"],role="remaining_family_development_increment",
                        public_package_sha256=row["sha256"],max_jobs=0,required=["report.json","public task.json criteria"])
        path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf8")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("prepare","run"))
    a=p.parse_args()
    if a.action=="prepare":
        prepare()
    else:
        errors=[]
        for i,task in enumerate(read(OUT/"intake_families.json")["selected"]):
            for arm in (reversed(ARMS) if i%2==0 else ARMS):
                try:
                    run(task,arm)
                    print(task,arm,"sealed",flush=True)
                except (OSError,RuntimeError,ValueError) as exc:
                    errors.append((task,arm,type(exc).__name__,str(exc)))
                    print(task,arm,type(exc).__name__,flush=True)
        if errors:
            raise RuntimeError(errors)
