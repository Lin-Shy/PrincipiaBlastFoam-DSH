"""Audit an early DeepSeek Flash run without reading gold or changing results."""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import time


def load(path: Path):
    return json.loads(path.read_text())


def audit(root: Path, count: int) -> dict:
    spec = importlib.util.spec_from_file_location("frozen_flash_preflight_navigation_qa", root / "navigation_qa.py")
    if spec is None or spec.loader is None:
        raise ValueError("cannot load frozen navigation decoder")
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    results = sorted(root.glob("*/sessions/*/result.json"), key=lambda p: p.stat().st_mtime_ns)[:count]
    records = []
    for result in results:
        for artifact in sorted(result.parent.glob("*.json")):
            value = load(artifact)
            if "request_sha256" in value:
                records.append(artifact)

    models = Counter()
    record_statuses = Counter()
    result_statuses = Counter()
    actions = Counter()
    issues = []
    valid_answers = 0
    model_invalid_actions = 0
    for path in records:
        record = load(path)
        record_statuses[record.get("status")] += 1
        model = (record.get("raw_response") or {}).get("model")
        models[str(model)] += 1
        if record.get("raw_response") and model != "deepseek-flash":
            issues.append({"file": str(path.relative_to(root)), "issue": "provider_model", "value": model})

    for path in results:
        result = load(path)
        result_statuses[result.get("status")] += 1
        parsed = result.get("parsed_answer")
        if isinstance(parsed, dict) and set(parsed) >= {"answer", "references", "unknowns"}:
            valid_answers += 1
        elif result.get("status") == "complete":
            issues.append({"file": str(path.relative_to(root)), "issue": "complete_without_answer_contract"})
        for event in result.get("events", []):
            action = event.get("action")
            name = action.get("action") if isinstance(action, dict) else None
            actions[str(name)] += 1
            response = load(path.parent / event["response_file"])
            decoded = frozen.decode_action(frozen.choice(response))
            if decoded != action:
                issues.append({"file": str(path.relative_to(root)), "issue": "stored_action_decode_mismatch",
                               "step": event.get("step"), "stored": action, "decoded": decoded})
            elif not isinstance(name, str):
                model_invalid_actions += 1

    session_text = "".join(
        artifact.read_text(errors="replace")
        for result in results
        for artifact in result.parent.rglob("*.json")
    )
    passed = (
        len(results) == count
        and not issues
        and set(result_statuses) <= {"complete", "incomplete_answer"}
        and models == {"deepseek-flash": len(records)}
        and "TypeError" not in session_text
    )
    return {
        "schema": "deepseek-flash-first-results-preflight-v2",
        "created_unix_ns": time.time_ns(),
        "scope": f"first {count} completed result files by completion time and their API records",
        "result_files": [str(path.relative_to(root)) for path in results],
        "completed_results": len(results),
        "result_statuses": dict(result_statuses),
        "api_records": len(records),
        "api_record_statuses": dict(record_statuses),
        "provider_models": dict(models),
        "normalized_event_actions": dict(actions),
        "model_invalid_action_events": model_invalid_actions,
        "answers_with_required_parsed_keys": valid_answers,
        "type_error_text_occurrences": session_text.count("TypeError"),
        "issues": issues,
        "passed": passed,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--run", type=Path, required=True)
    cli.add_argument("--count", type=int, default=30)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    report = audit(args.run.resolve(), args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "result_files"}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
