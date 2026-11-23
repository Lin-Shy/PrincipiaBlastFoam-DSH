"""Data-only client for the laminar pipe development pair."""
import argparse
import json
import math
import os
import time
from pathlib import Path


def validate(case):
    if not isinstance(case, dict) or set(case) != {"rows"} or not isinstance(case["rows"], list) or len(case["rows"]) != 65:
        raise ValueError("expected 65 radial rows")
    for index, row in enumerate(case["rows"]):
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError("expected five numbers per row")
        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e15 for v in row):
            raise ValueError("invalid numeric coefficient")
        if abs(row[0] - index * .01 / 64) > 1e-12 or row[2] == 0:
            raise ValueError("unexpected grid or zero diagonal")


def main(action):
    exchange = Path("pipe_exchange")
    if action == "submit":
        case = json.loads(Path("case.json").read_text(encoding="utf-8-sig"))
        validate(case)
        exchange.mkdir(exist_ok=True)
        temporary = exchange / f"incoming-{os.getpid()}.tmp"
        temporary.write_text(json.dumps(case, allow_nan=False), encoding="ascii")
        try:
            os.link(temporary, exchange / "request.json")
        finally:
            temporary.unlink()
        print("registered; collect waits for node receipt")
        return
    for _ in range(60):
        if (exchange / "failure.json").is_file():
            raise RuntimeError((exchange / "failure.json").read_text())
        if (exchange / "receipt.json").is_file():
            print("available: pipe_exchange/profile.csv and pipe_exchange/receipt.json")
            return
        time.sleep(1)
    print("pending; call collect again")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["submit", "collect"])
    main(parser.parse_args().action)
