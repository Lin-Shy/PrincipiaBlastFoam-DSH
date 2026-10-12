"""Verify every copied and canonical artifact in a candidate 010 reuse archive."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(archive):
    archive = Path(archive).resolve()
    manifest = json.loads((archive / "manifest.json").read_text())
    failures = []
    for artifact in manifest["artifacts"]:
        path = (archive / artifact["path"]).resolve()
        if not path.is_file():
            failures.append({"path": artifact["path"], "reason": "missing"})
        elif path.stat().st_size != artifact["bytes"]:
            failures.append({"path": artifact["path"], "reason": "size"})
        elif sha256(path) != artifact["sha256"]:
            failures.append({"path": artifact["path"], "reason": "sha256"})
    return {
        "status": "passed" if not failures else "failed",
        "checked": len(manifest["artifacts"]),
        "failures": failures,
        "frozen_graph_sha256": manifest["frozen_graph_sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.archive)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
