"""零模型汇总冻结的数据审核调用、结构和传输成本。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new accounting version required")
    protocol_file = args.review / "protocol.json"
    protocol = json.loads(protocol_file.read_text())
    rows, status, usage, attempts, identity_errors = [], Counter(), Counter(), 0, []
    for key, expected in protocol["packets"].items():
        packet_file = args.review / "packets" / (key + ".json")
        if sha(packet_file) != expected:
            raise ValueError("packet drift")
        folder = args.review / "responses" / key
        compiled_file, response_file = folder / "compiled.json", folder / "review.json"
        if not compiled_file.exists():
            rows.append({"id": key, "status": "missing"})
            status["missing"] += 1
            continue
        compiled = json.loads(compiled_file.read_text())
        response = json.loads(response_file.read_text())
        if compiled["response_sha256"] != sha(response_file) or compiled["packet_sha256"] != expected:
            raise ValueError("compiled artifact drift")
        raw = response["raw_response"]
        if response["request"]["model"] != protocol["model"] or raw["model"] != protocol["model"]:
            identity_errors.append(key)
        if response["request"]["enable_thinking"] is not False or response["request"]["temperature"] != 0:
            raise ValueError("generation configuration drift")
        if response["request"]["response_format"] != {"type": "json_object"}:
            raise ValueError("response format drift")
        usage.update(raw.get("usage", {}))
        attempts += len(response["events"])
        status[compiled["status"]] += 1
        row = {"id": key, "status": compiled["status"], "response_sha256": sha(response_file),
               "compiled_sha256": sha(compiled_file), "candidate_accepted": compiled.get("candidate_accepted")}
        if "candidate_accepted" in compiled:
            row["review"] = compiled.get("review")
        rows.append(row)
    out = {"schema": "dataset-review-call-accounting-v1", "role": protocol["role"], "model": protocol["model"],
           "protocol_sha256": sha(protocol_file), "implementation_sha256": sha(Path(__file__)),
           "planned_calls": len(protocol["packets"]), "completed_calls": len(rows)-status["missing"],
           "statuses": dict(status), "accepted": sum(r.get("candidate_accepted") is True for r in rows),
           "attempts": attempts, "retries": attempts-(len(rows)-status["missing"]), "usage": dict(usage),
           "identity_errors": identity_errors, "rows": rows,
           "limits": "模型意见不替代语义独立性、源核验或人工盲审；仅汇总传输可见token，不是实际账单。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in {"rows", "limits"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
