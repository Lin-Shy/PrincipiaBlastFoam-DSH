"""只读核验冻结文件、原始语料与凭据未泄露；仅输出计数，不输出密钥。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--source-corpus", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identity = json.loads((args.archive/"corpus_manifest.json").read_text())
    source_drift = [row["path"] for row in identity["files"]
        if sha((args.source_corpus/row["path"]).read_bytes()) != row["sha256"]]
    runs = []
    for root in args.runs:
        protocol = json.loads((root/"protocol.json").read_text())
        drift = [path for path, expected in protocol["files"].items() if sha((root/path).read_bytes()) != expected]
        runs.append({"path":str(root),"protocol_sha256":sha((root/"protocol.json").read_bytes()),
                     "files":len(protocol["files"]),"drift":drift,
                     "completed_results":len(list(root.glob("*/sessions/*/result.json")))})
    secret = args.key_file.read_bytes().strip()
    if not secret:
        raise ValueError("Empty credential; scan cannot be meaningful")
    matches = scanned = 0
    for root in [args.archive,*args.runs]:
        for path in root.rglob("*"):
            if not path.is_file() or {"runtime","upstream","__pycache__"} & set(path.relative_to(root).parts):
                continue
            scanned += 1
            matches += secret in path.read_bytes()
    record = {"status":"PASS" if not source_drift and not matches and not any(r["drift"] for r in runs) else "FAIL",
        "timestamp_unix_ns":time.time_ns(),"original_corpus_files":len(identity["files"]),
        "original_corpus_drift":source_drift,"runs":runs,
        "credential_scan_files":scanned,"credential_literal_matches":matches,
        "note":"No secret or credential-derived hash is stored. Graphify installed source identities are additionally verified by frozen runner verify."}
    if args.output.exists():
        raise FileExistsError("Preserve prior verification")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(record,ensure_ascii=False))
    if record["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
