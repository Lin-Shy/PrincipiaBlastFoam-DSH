"""Finish a pipe-service upload interrupted after creation of the owned remote run."""
import argparse
import tarfile
import shlex
import time

from pair import ARMS,PAIR,base,read,sha,write
import cluster_job


def recover(arm,pair=PAIR,task=None):
    root = pair/arm
    state = root/"operator"
    if task is None:
        rid = "c3-couette-a01-"+arm+"-20261121"
        exchange="pipe_exchange"
        program="node_solve.py"
    else:
        if task not in {"C3X01","C3X02","C3X03","C3X04"} or pair!=base/"expansion_public_increment_20261121"/task:
            raise ValueError("unknown duct run")
        rid="c3-"+task.lower()+"-"+arm+"-20261121"
        exchange="node_exchange"
        program="duct_node.py"
    config = read(base/"pilot_decision_20261117/acceptance.config.json")
    intent = read(state/"stage_intent.json")
    remote = cluster_job.REMOTE_ROOT+"/"+rid
    if intent["remote"]!=remote or intent["run_id"]!=rid or (state/"submit_intent.json").exists():
        raise ValueError("not a recoverable pre-submission stage")
    if (state/"stage_receipt.json").exists():
        return
    source = state/"input"
    case = read(source/"case.json")
    if case!=read(root/"workspace"/exchange/"request.json"):
        raise ValueError("original case changed")
    if task is not None:
        manifest=read(pair/"manifest.json")
        expected=[v for n,v in manifest["source_sha256"].items() if n.endswith(program)]
        if expected!=[sha(source/program)] or (source/"run_case.sh").read_bytes()!=b"set -eu\nexec /usr/bin/python3 -I payload/duct_node.py\n":
            raise ValueError("fixed duct program changed")
    with tarfile.open(state/"payload.tar") as archive:
        names = {"payload/case.json","payload/"+program,"payload/run_case.sh"}
        if set(archive.getnames())!=names or not all(archive.getmember(n).isfile() and archive.extractfile(n).read()==(source/n.split("/")[-1]).read_bytes() for n in names):
            raise ValueError("stage bundle mismatch")
    if (state/"batch.sh").read_text(encoding="utf8")!=intent["batch_script"]:
        raise ValueError("stage script changed")
    # Signed-off local bytes only. Refuse conflicting files and directories.
    prefix = "set -eu; cd "+shlex.quote(remote)+"; test \"$(pwd -P)\" = "+shlex.quote(remote)+"; test \"$(stat -c %u .)\" = \"$(id -u)\"; "
    def remote_call(command,**kwargs):
        return cluster_job.ssh(config,prefix+command,**kwargs)
    for name in ("payload.tar","batch.sh"):
        local = state/name
        digest = sha(local)
        q = shlex.quote(name)
        fresh = shlex.quote(name+".transfer-"+str(time.time_ns()))
        command = ("if test ! -e "+q+"; then (set -C; cat > "+fresh+"); "
                   "test \"$(sha256sum "+fresh+" | cut -d' ' -f1)\" = "+digest+"; ln "+fresh+" "+q+"; fi; "
                   "test ! -L "+q+"; test \"$(sha256sum "+q+" | cut -d' ' -f1)\" = "+digest)
        remote_call(command,input=local.read_bytes(),capture_output=True)
    remote_call("if test ! -e payload; then tar -xf payload.tar; fi; test ! -L payload; "+
                " && ".join("test \"$(sha256sum "+shlex.quote("payload/"+p.name)+" | cut -d' ' -f1)\" = "+sha(p)
                            for p in source.iterdir()),capture_output=True)
    write(state/"stage_receipt.json",dict(run_id=rid,remote=remote,payload_sha256=sha(state/"payload.tar"),
                                          recovery="hash-verified existing owned directory"))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("arm",choices=ARMS)
    recover(p.parse_args().arm)
