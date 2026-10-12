"""冻结问答计量、证据下界与人工逐项评分合并；未审阅答案不自动判对。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import time


def read(path):
    return json.loads(path.read_text())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def citation_check(answer, seen):
    references = answer.get("references", []) if isinstance(answer, dict) else []
    if not isinstance(references, list):
        return [{"valid_seen_range": False, "reason": "references is not a list"}]
    result = []
    for index, ref in enumerate(references):
        valid = isinstance(ref, dict)
        if valid:
            path, start, end = ref.get("path"), ref.get("start"), ref.get("end")
            valid = isinstance(path, str) and type(start) is int and type(end) is int and 1 <= start <= end
            if valid:
                valid = all(str(n) in seen.get(path, {}) for n in range(start, end + 1))
        result.append({"index": index, "valid_seen_range": valid,
                       "semantic_support": "requires_review", "reason": "seen original lines" if valid else "missing/unseen/invalid range"})
    return result


def evidence_lower_bound(annotation, seen):
    result = []
    for evidence in annotation["evidence"]:
        lines = evidence["quote"].splitlines()
        necessary = [(i, line) for i, line in enumerate(lines, evidence["start"]) if line.strip()]
        covered = sum(seen.get(evidence["path"], {}).get(str(i)) == line for i, line in necessary)
        result.append({"id": evidence["id"], "covered_nonblank_lines": covered,
                       "required_nonblank_lines": len(necessary), "complete": covered == len(necessary)})
    return result


def session_metrics(folder, annotation):
    path = folder / "result.json"
    result = read(path) if path.exists() else None
    events = result["events"] if result else [read(p) for p in sorted((folder / "tool_events").glob("*.json"))]
    calls = [e for e in events if "result" in e]
    actions = Counter(e["action"].get("action", "invalid_action") for e in calls)
    content = Counter()
    initialization = Counter()
    for event in calls:
        content.update(event["accounting"]["content"])
        init = event["accounting"].get("initialization")
        if init:
            initialization.update(init["content"])
    responses = [read(p) for p in sorted(folder.glob("step-*.json"))]
    if (folder / "final.json").exists():
        responses.append(read(folder / "final.json"))
    usage = Counter()
    attempts, failures, missing, unknown_seconds = 0, 0, 0, 0
    api_seconds = 0.0
    transmitted = Counter()
    for response in responses:
        reported = response.get("raw_response", {}).get("usage")
        for attempt in response["events"]:
            attempts += 1
            failures += attempt["status"] == "transport_error"
            if isinstance(attempt.get("seconds"), (int, float)):
                api_seconds += attempt["seconds"]
            else:
                unknown_seconds += 1
            actual_usage = attempt.get("usage")
            # Historical runners stored successful usage only on raw_response.
            if not actual_usage and attempt["status"] == "response":
                actual_usage = reported
            if not actual_usage or "total_tokens" not in actual_usage:
                missing += 1
            if actual_usage:
                for name in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                    if name in actual_usage:
                        usage[name] += actual_usage[name]
            # Charge repeated request contexts for every attempted transmission.
            body = response.get("request", {})
            transmitted["request_body_characters"] += len(wire(body))
            for message in body.get("messages", []):
                content_text = message.get("content", "")
                content_text = content_text if isinstance(content_text, str) else wire(content_text)
                transmitted["message_content_characters"] += len(content_text)
                if content_text.startswith("Tool result: "):
                    transmitted["tool_context_message_characters"] += len(content_text)
    final_usage = read(folder / "final.json").get("raw_response", {}).get("usage", {}) if (folder / "final.json").exists() else {}
    invocations = [read(p) for p in (folder / "invocations").glob("*.json")]
    measured_invocations = [x for x in invocations if not x["replay"]]
    unknown_wall = sum(not isinstance(x.get("elapsed_seconds"), (int, float)) for x in measured_invocations)
    wall = sum(x["elapsed_seconds"] for x in measured_invocations if isinstance(x.get("elapsed_seconds"), (int, float)))
    seen = result.get("seen_lines", {}) if result else {}
    evidence = evidence_lower_bound(annotation, seen)
    citations = citation_check(result.get("parsed_answer"), seen) if result else []
    metrics = {"session": folder.name, "item_id": annotation["id"], "category": annotation["category"],
        "method": result["method"] if result else folder.name.split("--")[1],
        "status": result["status"] if result else "unfinished_or_failed",
        "quality_reviewed": False, "qa_success": None, "first_answer_success": None,
        "tool_calls": len(calls), "graph_queries": actions["locate"], "file_search_calls": actions["search"],
        "catalog_calls": actions["catalog"], "source_read_calls": actions["source"],
        "all_source_read_operations": actions["source"] + content["internal_source_read_operations"],
        "initialization_source_read_operations": initialization["internal_source_read_operations"],
        "repeated_search_calls": sum(e["accounting"]["repeat"] for e in calls),
        "failed_tool_calls": sum(e["result"].get("status") not in ("ok", "no_match") for e in calls),
        "empty_search_calls": sum(e["action"].get("action") == "search" and not e["result"].get("items") for e in calls),
        "internal_content": dict(content), "initialization_content": dict(initialization),
        "returned_context_characters": sum(e["returned_characters"] for e in calls),
        "returned_context_tokens_estimated_chars_div4": sum(e["returned_characters"] for e in calls) / 4,
        "reported_model_usage": dict(usage), "reported_total_model_tokens": usage["total_tokens"],
        "answer_tokens": final_usage.get("completion_tokens"),
        "transport_attempts": attempts, "transport_failures": failures, "model_calls_with_response": sum(r["status"] == "response" for r in responses),
        "transport_retries": sum(max(0, len(r["events"])-1) for r in responses),
        "unresolved_transport_attempts": sum(e["status"] in ("in_flight", "interrupted_unresolved") for r in responses for e in r["events"]),
        "attempted_request_content": dict(transmitted),
        "unknown_usage_attempts": missing, "all_attempts_model_tokens": usage["total_tokens"] if not missing else None,
        "retrieval_seconds": sum(e["accounting"]["seconds"] for e in calls), "api_seconds": api_seconds,
        "unknown_api_duration_attempts": unknown_seconds,
        "session_seconds": wall, "unknown_session_duration_invocations": unknown_wall,
        "all_invocations_session_seconds": wall if not unknown_wall else None,
        "component_seconds": api_seconds + sum(e["accounting"]["seconds"] for e in calls),
        "required_evidence_full_span_lower_bound": statistics.mean(x["complete"] for x in evidence) if evidence else None,
        "evidence_details": evidence, "citation_range_checks": citations,
        "first_policy_complied": result.get("first_policy_complied") if result else None,
        "answer_sha256": sha(result["answer"].encode()) if result else None,
        "trace_sha256": sha(path.read_bytes()) if result else None,
        "annotation_sha256": sha(wire(annotation).encode())}
    return metrics


REVIEW_DIMENSIONS = {
    "concept_accuracy", "case_accuracy", "file_dictionary_accuracy", "manual_accuracy",
    "cross_source_completeness", "required_evidence_recall", "citation_accuracy",
    "evidence_status_accuracy", "ambiguity_accuracy",
}


def merge_review(metrics, review, annotation, scoring, seen):
    for field in ("answer_sha256", "trace_sha256", "annotation_sha256"):
        if review.get(field) != metrics[field]:
            raise ValueError("review identity mismatch: " + field)
    points = review.get("gold_points", [])
    if len(points) != len(annotation["gold"]) or any(p.get("score") not in (0, 1, 2) or not p.get("reason") for p in points):
        raise ValueError("incomplete point review")
    dimensions = review.get("dimensions", {})
    if "quality" in scoring:
        expected = set(scoring["quality"]) - {"qa_success", "first_answer_success", "answer_accuracy"}
    elif scoring.get("schema") in ("natural-navigation-scoring-v2", "natural-navigation-scoring-v7-20-80"):
        expected = REVIEW_DIMENSIONS
    else:
        raise ValueError("unsupported scoring-rule schema")
    if set(dimensions) != expected or not review.get("reviewer"):
        raise ValueError("missing quality dimensions or reviewer")
    for dimension, score in dimensions.items():
        if score is not None and (type(score) not in (int, float) or not 0 <= score <= 1):
            raise ValueError("invalid score for " + dimension)
    applicable = {"required_evidence_recall", "citation_accuracy", "evidence_status_accuracy"}
    if annotation["concepts"]:
        applicable.add("concept_accuracy")
    if annotation["cases"]:
        applicable.add("case_accuracy")
    if annotation["targets"]:
        applicable.add("file_dictionary_accuracy")
    if annotation["category"] != "tutorial":
        applicable.add("manual_accuracy")
    if annotation["category"] == "cross":
        applicable.add("cross_source_completeness")
    if annotation["ambiguity"]:
        applicable.add("ambiguity_accuracy")
    if any(dimensions[d] is None for d in applicable):
        raise ValueError("applicable quality metric cannot be null")
    for point in points:
        if point["score"] == 2 and not point.get("support"):
            raise ValueError("fully correct point needs seen source support")
        for support in point.get("support", []):
            path, start, end = support["path"], support["start"], support["end"]
            if type(start) is not int or type(end) is not int or not 1 <= start <= end:
                raise ValueError("invalid review support range")
            if not all(str(i) in seen.get(path, {}) for i in range(start, end + 1)):
                raise ValueError("review support not seen by answering agent")
            raw = "\n".join(seen[path][str(i)] for i in range(start, end + 1))
            if not support.get("quote") or support["quote"] not in raw:
                raise ValueError("review support quote differs from seen source")
    citations = review.get("citations", [])
    if len(citations) != len(metrics["citation_range_checks"]) or any(not c.get("reason") for c in citations):
        raise ValueError("citation support review missing")
    if not isinstance(review.get("extra_errors"), list):
        raise ValueError("extra error audit missing")
    valid = all(c["valid_seen_range"] for c in metrics["citation_range_checks"])
    supported = bool(citations) and all(c.get("supported") is True for c in citations)
    success = (metrics["status"] == "complete" and all(p["score"] == 2 for p in points) and valid and supported
               and not review["extra_errors"] and dimensions["required_evidence_recall"] == 1
               and dimensions["citation_accuracy"] == 1
               and all(dimensions[d] in (None, 1) for d in ("concept_accuracy", "case_accuracy", "file_dictionary_accuracy",
                                                          "manual_accuracy", "cross_source_completeness", "evidence_status_accuracy", "ambiguity_accuracy")))
    metrics.update(dimensions, quality_reviewed=True, answer_accuracy=statistics.mean(p["score"]/2 for p in points),
                   qa_success=success, first_answer_success=success, review=review)
    return metrics


def summarize(run, reviews=None, output=None):
    protocol = read(run / "protocol.json")
    for name, expected in protocol["files"].items():
        if sha((run / name).read_bytes()) != expected:
            raise ValueError("frozen artifact changed: " + name)
    annotations = {a["id"]: a for a in read(run / "evaluation_only/annotations.json")}
    rules = read(run / "evaluation_only/scoring-rules.json")
    review_rows = {x["session"]: x for x in read(reviews)} if reviews else {}
    rows = []
    for folder in sorted((run / "sessions").glob("*")):
        if not folder.is_dir():
            continue
        qid = folder.name.split("--")[0].split("-p")[0]
        metrics = session_metrics(folder, annotations[qid])
        if folder.name in review_rows:
            merge_review(metrics, review_rows[folder.name], annotations[qid], rules, read(folder / "result.json")["seen_lines"])
        rows.append(metrics)
    groups = defaultdict(list)
    for row in rows:
        groups[row["method"], row["category"]].append(row)
        groups[row["method"], "overall"].append(row)
    summary = []
    for (method, category), group in sorted(groups.items()):
        numeric = ("tool_calls", "graph_queries", "file_search_calls", "source_read_calls", "all_source_read_operations",
                   "repeated_search_calls", "failed_tool_calls", "returned_context_characters", "reported_total_model_tokens",
                   "retrieval_seconds", "session_seconds", "unknown_usage_attempts", "required_evidence_full_span_lower_bound")
        reviewed = [x for x in group if x["quality_reviewed"]]
        summary.append({"method": method, "category": category, "n": len(group), "reviewed": len(reviewed),
                        "successes": sum(x["qa_success"] for x in reviewed) if reviewed else None,
                        "means": {k: statistics.mean(x[k] for x in group) for k in numeric},
                        "note": "Reported token totals exclude unknown failed-request usage; no cost-saving claim from these alone."})
    target = output or run / ("metrics-" + str(time.time_ns()) + ".json")
    save(target, {"protocol_sha256": sha((run / "protocol.json").read_bytes()), "sessions": rows, "summary": summary,
         "quality_gate": "unreviewed" if any(not x["quality_reviewed"] for x in rows) else "reviewed",
         "timing": "Parallel dispatch/graph lock time is included in tool and observed session latency. Common corpus load/index init are separate artifacts, not hidden savings.",
         "evidence": "Full-span evidence is a conservative structural lower bound. It is not answer correctness or semantic citation support."})
    print(wire({"output": str(target), "sessions": len(rows), "summary": summary}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--reviews", type=Path)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    summarize(a.run, a.reviews, a.output)
