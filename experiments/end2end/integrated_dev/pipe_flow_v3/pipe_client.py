"""Professional pipe client with operator admission and repeatable rejection feedback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from pipe_schema import validate
from pipe_preflight import check_direction

EXCHANGE = Path(__file__).resolve().parent.parent/"pipe_exchange"


def submit():
    case = json.loads(Path("case.json").read_text(encoding="utf-8-sig"))
    validate(case)
    try:
        check_direction(case["rows"],driving_sign=1)
    except ValueError as exc:
        raise ValueError(f"{exc} With a positive center coefficient and negative neighbors, "
                         "the matrix represents minus diffusion. Its forcing is minus dp/dz. "
                         "Revisit the source term before registering; no job was consumed.") from exc
    EXCHANGE.mkdir(exist_ok=True)
    request = EXCHANGE/"request.json"
    pending = EXCHANGE/f"candidate-{os.getpid()}.tmp"
    with pending.open("x",encoding="ascii") as stream:
        json.dump(case,stream,allow_nan=False)
    try:
        if request.exists():
            key = hashlib.sha256(request.read_bytes()).hexdigest()
            rejection = EXCHANGE/(key+".rejected.json")
            if not rejection.is_file():
                raise FileExistsError("a candidate is registered; use collect")
            os.replace(pending,request)
        else:
            os.link(pending,request)
    finally:
        pending.unlink(missing_ok=True)
    print("registered for operator validation; collect reports status")


def collect():
    source = EXCHANGE/"request.json"
    if not source.is_file():
        raise ValueError("no registered candidate")
    key = hashlib.sha256(source.read_bytes()).hexdigest()
    for _ in range(60):
        for name in (key+".rejected.json","failure.json"):
            p = EXCHANGE/name
            if p.exists():
                raise ValueError(p.read_text(encoding="utf8"))
        receipt = EXCHANGE/"receipt.json"
        if receipt.exists():
            record = json.loads(receipt.read_bytes())
            case = json.loads(source.read_bytes())
            staged = json.dumps(case,ensure_ascii=False,indent=2).replace("\n",os.linesep).encode("utf8")
            profile = EXCHANGE/"profile.csv"
            if hashlib.sha256(staged).hexdigest()!=record["case_sha256"] or hashlib.sha256(profile.read_bytes()).hexdigest()!=record["profile_sha256"]:
                raise ValueError("staged case or returned profile differs")
            print(f"verified staged matrix and node output; copy {profile} and {receipt}")
            return
        time.sleep(1)
    print("pending; call collect again")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action",choices=("submit","collect"))
    if p.parse_args().action=="submit":
        submit()
    else:
        collect()
