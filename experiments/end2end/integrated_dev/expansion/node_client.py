"""Register one numeric linear system or wait for its owned node result."""
import argparse
import json
import math
import os
from pathlib import Path
import time


def validate(case,settings):
    if not isinstance(case,dict) or set(case)!={"nx","ny","matrix","rhs"}:
        raise ValueError("expected nx, ny, matrix, rhs")
    nx,ny = case["nx"],case["ny"]
    if type(nx)!=int or type(ny)!=int or (nx,ny)!=(settings["nx"],settings["ny"]):
        raise ValueError("grid dimensions differ from public package")
    n=(nx-1)*(ny-1)
    if not 1<=n<=256 or len(case["matrix"])!=n or len(case["rhs"])!=n:
        raise ValueError("invalid dimensions")
    if any(not isinstance(row,list) or len(row)!=n for row in case["matrix"]):
        raise ValueError("invalid matrix row")
    if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e14
           for row in [*case["matrix"],case["rhs"]] for v in row):
        raise ValueError("invalid coefficient")


def main(action):
    root=Path(__file__).resolve().parent.parent
    exchange=root/"node_exchange"
    if action=="submit":
        case=json.loads(Path("case.json").read_text(encoding="utf-8-sig"))
        validate(case,json.loads((root/"settings.json").read_bytes()))
        exchange.mkdir(exist_ok=True)
        tmp=exchange/f"candidate-{os.getpid()}.tmp"
        with tmp.open("x",encoding="utf8") as out:
            json.dump(case,out,allow_nan=False)
        try:
            os.link(tmp,exchange/"request.json")
        finally:
            tmp.unlink()
        print("registered; use collect")
        return
    for _ in range(60):
        if (exchange/"receipt.json").exists():
            print(f"available: {exchange/'field.json'} and {exchange/'receipt.json'}")
            return
        if (exchange/"failure.json").exists():
            raise RuntimeError((exchange/"failure.json").read_text(encoding="utf8"))
        time.sleep(1)
    print("pending; collect again")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("submit","collect"))
    main(p.parse_args().action)
