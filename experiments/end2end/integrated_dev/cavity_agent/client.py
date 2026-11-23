"""Data-only registration of the eight public OpenFOAM dictionaries."""
import json
from pathlib import Path
import sys,time
ROOT=Path(__file__).resolve().parent.parent
EXCHANGE=ROOT/"exchange"
FILES=("0/U","0/p","constant/transportProperties","system/blockMeshDict","system/controlDict","system/fvSchemes","system/fvSolution","system/setFieldsDict")
if sys.argv[1]=="submit":
    case=ROOT/"case"
    payload={n:(case/n).read_text(encoding="utf-8-sig") for n in FILES}
    EXCHANGE.mkdir(exist_ok=True)
    with (EXCHANGE/"request.json").open("x",encoding="utf8") as f:json.dump(payload,f)
    print("registered once; use collect")
elif sys.argv[1]=="collect":
    for _ in range(55):
        if (EXCHANGE/"receipt.json").exists():
            print((EXCHANGE/"receipt.json").read_text());break
        if (EXCHANGE/"failure.json").exists():
            raise RuntimeError((EXCHANGE/"failure.json").read_text())
        time.sleep(1)
    else:print("pending; repeat collect, never submit again")
else:raise ValueError("submit or collect")
