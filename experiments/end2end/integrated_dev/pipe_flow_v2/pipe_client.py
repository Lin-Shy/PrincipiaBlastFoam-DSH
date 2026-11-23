"""PIPE-01 v2. Locate the exchange relative to the installed client."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from pipe_schema import validate


def submit(exchange):
    case = json.loads(Path("case.json").read_text(encoding="utf-8-sig"))
    validate(case)
    checker = Path(__file__).with_name("pipe_preflight.py")
    if checker.is_file():
        from pipe_preflight import check_direction
        check_direction(case["rows"], driving_sign=1)
    exchange.mkdir(exist_ok=True)
    temporary = exchange/f"incoming-{os.getpid()}.tmp"
    with temporary.open("x",encoding="ascii") as out:
        json.dump(case,out,allow_nan=False)
    try:
        os.link(temporary,exchange/"request.json")
    finally:
        temporary.unlink()
    print("registered; collect returns the absolute result directory")


def collect(exchange):
    for _ in range(60):
        if (exchange/"failure.json").exists():
            raise RuntimeError((exchange/"failure.json").read_text(encoding="utf8"))
        if (exchange/"receipt.json").exists():
            receipt = json.loads((exchange/"receipt.json").read_bytes())
            case = json.loads((exchange/"request.json").read_bytes())
            staged_bytes = json.dumps(case,ensure_ascii=False,indent=2).encode("utf8")
            # The Windows operator's JSON writer uses the platform's text newline.
            staged_bytes = staged_bytes.replace(b"\n",os.linesep.encode("ascii"))
            if hashlib.sha256(staged_bytes).hexdigest() != receipt["case_sha256"]:
                raise ValueError("node input digest differs from registered matrix")
            if hashlib.sha256((exchange/"profile.csv").read_bytes()).hexdigest() != receipt["profile_sha256"]:
                raise ValueError("profile digest mismatch")
            print(f"verified staged matrix and profile. case_sha256 covers the operator's "
                  f"reserialized JSON. Results: {exchange/'profile.csv'} and {exchange/'receipt.json'}")
            return
        time.sleep(1)
    print("pending; call collect again")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action",choices=["submit","collect"])
    exchange = Path(__file__).resolve().parent.parent/"pipe_exchange"
    if parser.parse_args().action == "submit":
        submit(exchange)
    else:
        collect(exchange)
