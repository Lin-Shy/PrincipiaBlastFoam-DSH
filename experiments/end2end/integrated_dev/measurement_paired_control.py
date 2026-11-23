"""Compare frozen native catalogs and replay measurement operations on sealed public work."""
import json
import math
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from measurement_replay import wave, HERE, read, write, sha, OUT as PRIOR
from measurement_live import DATA as DIAGNOSTIC, TEMPLATE
from runtime_config import prepare, runtime_node
from local_first_wave import common_environment, runtime
from measurement_profile import extend_profile

OUT = PRIOR.parent / "measurement_paired_control_20261122"
OLD = wave.OUT
NEW_TOOLS = {"pipe":"convert_volume_rates","coverage":"interval_coverage","restart":"latest_attempt_events"}


def dispatch_tool(root, cwd, name, args):
    env = dict(common_environment(root), C3_RUNTIME=str(runtime),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(HERE.parent))
    cmd = [runtime_node(runtime),str(HERE/"driver.mjs"),str(runtime),str(root),"professional",
           "invoke" if name else "catalog",name or "",json.dumps(args)]
    run = subprocess.run(cmd,cwd=cwd,env=env,capture_output=True,text=True,encoding="utf8",check=True)
    return json.loads(run.stdout.strip().splitlines()[-1])


def profiles():
    roots={}
    for revision in ["old","revised"]:
        root=OUT/"profiles"/revision
        root.mkdir(parents=True)
        for d in ["home","tmp","user","cache","agents_home"]:
            (root/d).mkdir()
        shutil.copytree(TEMPLATE/"skills",root/"skills")
        dump=(TEMPLATE/"dump.yml").read_text(encoding="utf8").replace(str(TEMPLATE),str(root))
        if revision=="revised":
            dump=extend_profile(dump,root)
        (root/"dump.yml").write_text(dump,encoding="utf8")
        prepare(root,runtime)
        result=dispatch_tool(root,OUT,None,{})
        write(root/"catalog.json",result)
        roots[revision]=root
    return roots


def parameters(family, s, rows):
    if family=="coverage":
        return dict(window=s["window"],intervals=[[r["start"],r["end"]] if r["valid"] else None for r in rows])
    if family=="restart":
        return dict(job=s["job"],events=[dict(r,time=r["time_s"]) for r in rows],writeEvent="WRITE",terminalEvents=["DONE","FAIL"])
    return {"values":[math.pi*((r["outer_mm"]/1000)**2-(r["inner_mm"]/1000)**2)*r["u_m_s"] for r in rows],
            "from":"m3/s","to":"L/s"}


def grade(data, task, report_path):
    proc=subprocess.run([sys.executable,"-B",str(data/"pack.py"),"grade",task,str(report_path)],capture_output=True,encoding="utf8")
    result=json.loads(proc.stdout)
    assert proc.returncode==int(not result["pass"])
    return result["fields"]


def main():
    OUT.mkdir(exist_ok=False)
    roots=profiles()
    catalogs={k:read(v/"catalog.json") for k,v in roots.items()}
    assert set(catalogs["revised"]["tools"])-set(catalogs["old"]["tools"])==set(NEW_TOOLS.values())
    assert set(catalogs["old"]["tools"])<=set(catalogs["revised"]["tools"])
    rows_out=[]
    for cohort,data in [("original",wave.DATA),("diagnostic",DIAGNOSTIC)]:
        for item in read(data/"READY.json")["tasks"]:
            task,family=item["id"],item["family"]
            package=data/item["archive"]
            assert sha(package)==item["sha256"]
            target=OUT/cohort/task
            target.mkdir(parents=True)
            with zipfile.ZipFile(package) as z:
                settings=json.loads(z.read("settings.json"))
                rows=json.loads(z.read("records.json"))
                for n in ["settings.json","records.json","task.json"]:
                    (target/n).write_bytes(z.read(n))
            result=None
            if family in NEW_TOOLS:
                name=NEW_TOOLS[family]
                params=parameters(family,settings,rows)
                native=dispatch_tool(roots["revised"],target,name,dict(input=json.dumps(params)))
                write(target/"tool.json",native["calls"][0])
                result=json.loads(native["calls"][0]["result"]["content"][0]["text"])
                terms=result["values"] if family=="pipe" else result["increments"]
                amount=sum(terms) if family=="pipe" else result["uncovered"] if family=="coverage" else result["distinct"]
                terminal=family!="restart" or result["terminal"]=="DONE"
                calculated=dict(amount=amount,terms=terms,decision="release" if terminal and settings["band"][0]<=amount<=settings["band"][1] else "hold")
            submissions={"professional":PRIOR/"live"/task/"professional"} if cohort=="diagnostic" else {
                arm:OLD/Path(segments["segments"][-1]["submission"]).parent for arm,segments in
                next(r["arms"] for r in read(OLD/"index.json")["tasks"] if r["task"]==task).items()}
            for arm,folder in submissions.items():
                archive=folder/"submission.zip"
                assert sha(archive)==read(folder/"sealed.json")["archive_sha256"]
                entry=dict(cohort=cohort,task=task,arm=arm,family=family,package_sha256=sha(package),
                           submission_sha256=sha(archive),applicable=result is not None)
                if result is not None:
                    with zipfile.ZipFile(archive) as z:
                        original=json.loads(z.read("report.json"))
                    before=target/(arm+"-before.json")
                    after=target/(arm+"-after.json")
                    write(before,original)
                    write(after,{**original,**calculated})
                    b,a=grade(data,task,before),grade(data,task,after)
                    entry.update(before=b,after=a,improved=[k for k in b if not b[k] and a[k]],
                                 regressed=[k for k in b if b[k] and not a[k]],
                                 value_changes=[k for k in a if original.get(k)!=read(after).get(k)])
                else:
                    entry["reason"]={"cavity":"circulation, no matching operation","balance":"volume, no native volume-to-volume conversion",
                                     "duct":"node field, no matching operation"}[family]
                rows_out.append(entry)
    write(OUT/"offline.json",dict(model_requests=0,jobs=0,rows=rows_out))


if __name__=="__main__":
    main()
