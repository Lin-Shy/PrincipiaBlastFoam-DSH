"""Keep only generation/review records that support selected v2 questions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MODEL = "deepseek-flash"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def request_questions(record: dict) -> tuple[str, ...]:
    messages = record.get("request", {}).get("messages", [])
    if not messages:
        return ()
    try:
        prompt = json.loads(messages[-1]["content"])
    except (KeyError, TypeError, ValueError):
        return ()
    questions = prompt.get("questions")
    return tuple(questions) if isinstance(questions, list) and all(isinstance(q, str) for q in questions) else ()


def response_questions(record: dict) -> tuple[str, ...]:
    try:
        content = record["response"]["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        value, _ = json.JSONDecoder(strict=False).raw_decode(content)
        if isinstance(value, dict) and set(value) == {"type", "content"}:
            value = value["content"]
            if isinstance(value, str):
                value, _ = json.JSONDecoder(strict=False).raw_decode(value)
        questions = value.get("questions") if isinstance(value, dict) else None
        return tuple(questions) if isinstance(questions, list) and all(isinstance(q, str) for q in questions) else ()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return ()


def prune(root: Path) -> dict:
    selected: dict[str, set[str]] = {}
    for split in ("dev", "holdout"):
        for row in read(root / f"{split}.questions.json"):
            legacy_id = row["id"].split("-n", 1)[0]
            selected.setdefault(legacy_id, set()).add(row["question"])
    records = root / "generation-records"
    kept, removed = [], []
    for path in sorted(records.rglob("*.json")):
        record = read(path)
        family = path.parent.name
        candidates = set(request_questions(record)) | set(response_questions(record))
        provider_model = (record.get("response") or {}).get("model")
        keep = (
            record.get("status") == "response"
            and provider_model == MODEL
            and bool(candidates & selected.get(family, set()))
        )
        if keep:
            kept.append(path)
        else:
            path.unlink()
            removed.append(path)
    for directory in sorted(records.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    failure_file = root / "generation-failures.json"
    if failure_file.exists():
        failure_file.unlink()

    manifest = read(root / "manifest.json")
    artifacts = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.relative_to(root).as_posix()] = sha(path)
    manifest["generation"] = {
        **manifest["generation"],
        "successful_api_records": len(kept),
        "record_retention": "only generation batches containing selected questions and both semantic reviews",
        "discarded_draft_or_superseded_records": len(removed),
    }
    manifest["artifacts"] = artifacts
    write(root / "manifest.json", manifest)
    return {"kept": len(kept), "removed": len(removed), "artifacts": len(artifacts)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prune(args.dataset.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
