"""Seal exhausted, structurally invalid blind reviews as null decisions.

This does not infer or alter a quality score. It makes the planned review grid
auditable while the quality report counts every invalid decision as failure.
"""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--minimum-attempts", type=int, default=4)
    args = parser.parse_args()
    root = args.reviews.resolve()
    journals = sorted((root / "invocations").glob("*.json"))
    if not journals:
        raise ValueError("missing review invocation")
    journal = read(journals[-1])
    if journal["status"] != "finished" or journal["packets"] != len(read(root / "evaluation_only/blind-map.json")):
        raise ValueError("final review invocation has not finished its full packet grid")
    mapping = read(root / "evaluation_only/blind-map.json")
    sealed = []
    for failure in journal["errors"]:
        blind_id = failure["blind_id"]
        if failure["error"] != "ValueError" or blind_id not in mapping:
            raise ValueError("unexpected review failure")
        folder = root / "sessions" / blind_id
        target = folder / "compiled.json"
        if target.exists():
            raise FileExistsError(target)
        attempts = sorted(folder.glob("review-*.json"))
        if len(attempts) < args.minimum_attempts:
            raise ValueError("review attempts are incomplete: " + blind_id)
        record = {
            "blind_id": blind_id,
            "binding": mapping[blind_id],
            "review_protocol_sha256": sha(root / "protocol.json"),
            "status": "invalid_structural_review",
            "adjudicated": False,
            "quality": None,
            "decision": None,
            "review_count": 0,
            "reason": f"At least {args.minimum_attempts} structural repair attempts exhausted; no score inferred",
            "attempt_files_sha256": {p.name: sha(p) for p in attempts},
            "failure_journal_sha256": sha(journals[0]),
        }
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        sealed.append(blind_id)
    print(json.dumps({"sealed_invalid_reviews": len(sealed), "blind_ids": sealed}))


if __name__ == "__main__":
    main()
