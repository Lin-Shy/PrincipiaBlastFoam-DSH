"""冻结正式输出的独立来源/调用重放与统计；不产生检索规则或模型调用。"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("native", "answers", "scores", "costs"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.output.exists():
        raise FileExistsError("new derived analysis version required")
    sys.path.insert(0, str(root / "runtime"))
    from chapter2_formal_runtime import verify, load, save, sha, jobs, ANSWER_ARMS
    from chapter2_family_statistics import paired_bootstrap, bounded_paired_bootstrap
    from chapter2_canonical_delivery import render
    from canonical_evidence_v1 import score
    from chapter2_native_dev_score import rank_metrics
    protocol, protocol_sha = verify(root, require_snapshot=False)
    output = {"schema": "formal-frozen-derived-" + args.stage + "-v1", "protocol_sha256": protocol_sha,
        "analysis_implementation_sha256": sha(Path(__file__)), "new_llm_calls": 0}
    if args.stage in {"native", "scores"}:
        annotation_file = Path(protocol["private_scoring_input"]["path"])
        if sha(annotation_file) != protocol["private_scoring_input"]["sha256"]:
            raise ValueError("private frozen scoring input drift")
        annotations = {a["id"]: a for a in load(annotation_file)}
    if args.stage == "native":
        for arm in protocol["native_arms"]:
            if not (root / "completion" / ("native--" + arm + ".json")).exists():
                raise ValueError("finish full native grid before scoring")
        corpus = Path(protocol["paths"]["corpus"])
        sources, checked_lines, rows = {}, 0, []
        def source(path):
            if path not in sources:
                raw = (corpus / path).read_bytes()
                sources[path] = (hashlib.sha256(raw).hexdigest(), raw.decode().splitlines())
            return sources[path]
        for annotation in annotations.values():
            for atom in annotation["evidence"]:
                source_hash, lines = source(atom["path"])
                quote = "\n".join(lines[atom["start"]-1:atom["end"]])
                if source_hash != atom["sha256"] or quote != atom["quote"]:
                    raise ValueError("gold source/quote drift")
        for key, repeat, question in jobs(protocol):
            for arm in protocol["native_arms"]:
                file = root / "native" / arm / (key + ".json")
                packet = load(file)
                if packet["protocol_sha256"] != protocol_sha or packet["question"] != question:
                    raise ValueError("native provenance drift")
                for unit in packet["canonical_units"]:
                    if unit.get("mapping_status") == "unmappable":
                        continue
                    source_hash, lines = source(unit["path"])
                    if source_hash != unit["source_sha256"] or lines[unit["start"]-1:unit["end"]] != unit["lines"]:
                        raise ValueError("native source-range drift")
                    checked_lines += len(unit["lines"])
                if arm == "no_cross" and any(step["cross_source"] for item in packet["native"]["items"] for step in item["route"]):
                    raise ValueError("cross-source ablation bypassed")
                if arm == "node_scan" and any(item["route"] for item in packet["native"]["items"]):
                    raise ValueError("node-scan traversed edges")
                annotation = annotations[question["family_id"]]
                metrics = rank_metrics(annotation["evidence"], render(packet["canonical_units"])["units"])
                budgets = {}
                for cap in protocol["budgets"] + [protocol["source_character_cap"]]:
                    delivery = render(packet["canonical_units"], cap)
                    actual = packet["answer_delivery"] if cap == protocol["source_character_cap"] else packet["deliveries"][str(cap)]
                    if delivery != actual or len(actual["text"]) > cap:
                        raise ValueError("actual delivery/cap drift")
                    budgets[str(cap)] = {**score(annotation["evidence"], delivery["units"], budgets=(cap,))["by_returned_character_budget"][str(cap)],
                        "actual_returned_characters": len(delivery["text"])}
                tutorial = [u for u in packet["deliveries"]["24000"]["units"] if u.get("mapping_status") != "unmappable" and u["source_kind"] == "tutorial" and u.get("case_id")]
                wrong = sum(u["case_id"].removeprefix("tutorials/") not in annotation["cases"] for u in tutorial)
                rows.append({"key": key, "question_id": question["id"], "family_id": question["family_id"], "repeat": repeat,
                    "category": annotation["category"], "arm": arm, "response_sha256": sha(file), "rank_metrics": metrics,
                    "by_budget": budgets, "query_seconds": packet["query_seconds"], "diagnostic": packet["diagnostic"],
                    "load_seconds": packet["load_seconds"], "framework_preload_seconds": packet["framework_preload_seconds"],
                    "scope_case_proxy": {"wrong_case_units": wrong, "identified_tutorial_units": len(tutorial),
                        "manual_only_wrong_source_units": len(tutorial) if annotation["category"] == "manual" else None},
                    "unmappable_native_units": sum(u.get("mapping_status") == "unmappable" for u in packet["canonical_units"])})
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["category"], row["arm"]].append(row)
        summaries = []
        for (category, arm), group in sorted(grouped.items()):
            families = defaultdict(list)
            for row in group:
                families[row["family_id"]].append(row)
            by_budget = {}
            for cap in protocol["budgets"] + [protocol["source_character_cap"]]:
                b = str(cap)
                by_budget[b] = {"question_repeat_complete_rate": statistics.mean(r["by_budget"][b]["complete_evidence_set_success"] for r in group),
                    "family_macro_complete_rate": statistics.mean(statistics.mean(r["by_budget"][b]["complete_evidence_set_success"] for r in values) for values in families.values()),
                    "family_macro_atom_recall": statistics.mean(statistics.mean(r["by_budget"][b]["recall"] for r in values) for values in families.values()),
                    "mean_returned_characters": statistics.mean(r["by_budget"][b]["actual_returned_characters"] for r in group)}
            wrong = sum(r["scope_case_proxy"]["wrong_case_units"] for r in group)
            denominator = sum(r["scope_case_proxy"]["identified_tutorial_units"] for r in group)
            summaries.append({"category": category, "arm": arm, "observations": len(group), "families": len(families), "by_budget": by_budget,
                "mean_query_seconds": statistics.mean(r["query_seconds"] for r in group),
                "wrong_case_association_proxy": wrong / denominator if denominator else None,
                "wrong_case_units": wrong, "identified_tutorial_units": denominator,
                "rank_metrics": {"mrr": statistics.mean(r["rank_metrics"]["mrr"] for r in group),
                    "top_k": {k: {m: statistics.mean(r["rank_metrics"]["top_k"][k][m] for r in group)
                        for m in ("recall", "precision", "complete_evidence_set_success", "ndcg_observed_candidate_pool")} for k in ("1", "3", "5", "10")}}})
        def outcomes(arm):
            out = defaultdict(list)
            for row in rows:
                if row["category"] == "cross" and row["arm"] == arm:
                    out[row["family_id"]].append(row["by_budget"]["24000"]["complete_evidence_set_success"])
            return dict(out)
        primary = paired_bootstrap(outcomes("full"), outcomes("no_cross"), resamples=protocol["statistics"]["paired_bootstrap_samples"], seed=protocol["seed"])
        output.update(rows=rows, summary=summaries, primary_comparison=primary, mechanism_supported=primary["difference"] > 0 and primary["ci95"][0] > 0,
            practical_8pp_target_met=primary["difference"] >= .08, source_files_checked=len(sources), authoritative_lines_checked=checked_lines,
            completed_native_queries=len(rows), limits="gold-only isolated scoring; observed-pool nDCG diagnostic and necessary-gold precision lowerbound; wrong-case proxy not exhaustive role semantics; no end-to-end success claim")
    elif args.stage == "answers":
        for arm in ANSWER_ARMS:
            if not (root / "completion" / ("answer--" + arm + ".json")).exists():
                raise ValueError("finish allsix answer grids before replay")
        import navigation_qa as qa
        import graphify_qa as net
        from chapter2_aliyun_config import configure_qa
        from chapter2_common_planner import compile_plan
        from chapter2_cited_answer import validate, answer_text, verification_feedback
        configure_qa(qa)
        net.SECRET = None
        counts = Counter()
        fingerprints = {}
        for key, repeat, question in jobs(protocol):
            folder = root / "planner" / key
            body = qa.request([{"role": "system", "content": protocol["prompts"]["planner"]},
                {"role": "user", "content": qa.wire({"question": question["question"]})}], final=False)
            response = net.fetch(folder, "plan", body, None)
            compiled = load(folder / "compiled.json")
            try:
                choice = qa.choice(response)
                if choice["finish_reason"] != "stop":
                    raise ValueError("planning response truncated")
                plan = compile_plan(qa.decode_json_prefix(choice["message"]["content"]), question["question"])
                status = "valid_structure"
            except (ValueError, TypeError, KeyError):
                plan = {"translation": "", "needs": [], "identifiers": []}
                status = "invalid_structure"
            if compiled["status"] != status or compiled["plan"] != plan or compiled["response_sha256"] != sha(folder / "plan.json"):
                raise ValueError("planner replay mismatch")
            counts["planner:" + status] += 1
            for arm in ANSWER_ARMS:
                native_file = root / "native" / arm / (key + ".json")
                packet = load(native_file)
                delivery = render(packet["canonical_units"], protocol["source_character_cap"])
                if delivery != packet["answer_delivery"]:
                    raise ValueError("answer evidence render drift")
                folder = root / "answers" / arm / key
                compiled = load(folder / "compiled.json")
                if compiled["native_response_sha256"] != sha(native_file) or compiled["protocol_sha256"] != protocol_sha:
                    raise ValueError("answer provenance drift")
                messages = [{"role": "system", "content": protocol["prompts"]["draft"]},
                    {"role": "user", "content": "公开问题：" + question["question"] + "\n权威原文：\n" + delivery["text"]}]
                draft = net.fetch(folder, "draft", qa.request(messages, final=True), None)
                try:
                    text = qa.choice(draft)["message"]["content"]
                except (ValueError, TypeError, KeyError):
                    text = ""
                feedback = verification_feedback(draft, delivery, qa)
                chars = len(delivery["text"]) + len(feedback) + len("程序坐标检查：")
                if chars > protocol["return_character_cap"] or chars != compiled["actual_source_feedback_characters"]:
                    raise ValueError("actual answer character cap drift")
                messages += [{"role": "assistant", "content": text}, {"role": "user", "content": protocol["prompts"]["verify"] + "\n程序坐标检查：" + feedback}]
                final = net.fetch(folder, "final", qa.request(messages, final=True), None)
                try:
                    choice = qa.choice(final)
                    if choice["finish_reason"] != "stop":
                        raise ValueError("final response truncated")
                    answer = validate(qa.decode_json_prefix(choice["message"]["content"]), delivery)
                    status, actual = "complete_structure", answer_text(answer, delivery)
                except (ValueError, TypeError, KeyError):
                    status, answer, actual = "incomplete", None, None
                if compiled["status"] != status or compiled["answer"] != answer or compiled["answer_text"] != actual:
                    raise ValueError("frozen final replay mismatch")
                counts[arm + ":" + status] += 1
                for name in ("draft", "final"):
                    if compiled["artifact_sha256"][name + ".json"] != sha(folder / (name + ".json")):
                        raise ValueError("raw answer artifact drift")
                fingerprints[str((folder / "compiled.json").relative_to(root))] = sha(folder / "compiled.json")
        output.update(replay_counts=dict(counts), answer_sessions=len(fingerprints), artifact_sha256=fingerprints,
            limits="API calls0; deterministic request/response/source-coordinate replay, not semantic correctness; no existing request files written because allverifiedresponses existed")
    elif args.stage == "scores":
        for shard in range(protocol["scoring_shards"]):
            for name in ("review", "adjudication"):
                if not (root / "completion" / (name + "--" + str(shard) + ".json")).exists():
                    raise ValueError("finish all scoring/adjudication shards first")
        from chapter2_pointwise_review import validate as review_validate
        import navigation_qa as qa
        import graphify_qa as net
        from chapter2_aliyun_config import configure_qa
        configure_qa(qa)
        net.SECRET = None
        manifest = load(root / "evaluation_only/review_jobs.json")
        prepared = load(root / "completion/review_prepare.json")
        if sha(root / "evaluation_only/review_jobs.json") != prepared["review_jobs_sha256"]:
            raise ValueError("prepared scoring manifest drift")
        identity = load(root / "evaluation_only/identity.json")
        if sha(root / "evaluation_only/identity.json") != manifest["identity_sha256"]:
            raise ValueError("blind identity drift")
        judgments, statuses, record_hashes = defaultdict(dict), Counter(), {}
        for key, job in manifest["jobs"].items():
            packet_file = root / "evaluation_only/review_packets" / (key + ".json")
            if sha(packet_file) != job["packet_sha256"]:
                raise ValueError("scoring packet drift")
            packet = load(packet_file)
            selected = None
            for stage in ("reviews", "adjudications"):
                folder = root / "evaluation_only" / stage / key
                if not folder.exists():
                    if stage == "reviews":
                        raise ValueError("missing primary judgment")
                    continue
                if stage == "adjudications" and selected["status"] == "valid_structure" and not (job["kind"] == "citations" and selected["review"]["state"] == "uncertain"):
                    raise ValueError("unregistered quality adjudication")
                compiled = load(folder / "compiled.json")
                prompt = protocol["prompts"]["point" if job["kind"] == "point" else "citations"]
                if stage == "adjudications":
                    prompt += "\n这是预注册的一次必要裁决。此前输出结构无效或支持性无法确定；请独立核验原材料并严格遵守字段与枚举。不改变实际回答，不补写事实，材料仍不足时保留不确定。"
                response = net.fetch(folder, "review", qa.request([{"role": "system", "content": prompt},
                    {"role": "user", "content": qa.wire(packet)}], final=False), None)
                try:
                    choice = qa.choice(response)
                    if choice["finish_reason"] != "stop":
                        raise ValueError("review response truncated")
                    value = review_validate(qa.decode_json_prefix(choice["message"]["content"]), packet, job["kind"])
                    status = "valid_structure"
                except (ValueError, KeyError, TypeError):
                    status, value = "invalid_structure", None
                if compiled["status"] != status or compiled["review"] != value or compiled["response_sha256"] != sha(folder / "review.json") or compiled["protocol_sha256"] != protocol_sha or compiled["packet_sha256"] != job["packet_sha256"]:
                    raise ValueError("scoring replay mismatch")
                record_hashes[str((folder / "compiled.json").relative_to(root))] = sha(folder / "compiled.json")
                statuses[stage + ":" + status] += 1
                selected = compiled
            judgments[job["blind_id"]]["citations" if job["kind"] == "citations" else "p" + str(job["point_index"])] = selected
        rows = []
        for blind, item in identity.items():
            packet = load(root / "evaluation_only/blind_packets" / (blind + ".json"))
            scores = judgments[blind]
            criteria, satisfied = [], 0
            for point in packet["gold_points"]:
                record = scores["p" + str(point["index"])]
                if record["status"] != "valid_structure":
                    criteria.append(None)
                else:
                    v = record["review"]
                    passed = v["assessment"] == "satisfied" and v["support"] == "supported"
                    satisfied += int(v["assessment"] == "satisfied")
                    criteria.append(passed)
            cite = scores["citations"]
            state = cite["review"]["state"] if cite["status"] == "valid_structure" else None
            criteria.append(True if state == "supported" else False if state == "unsupported" else None)
            if item["answer_structure"] != "complete_structure" or False in criteria:
                lower, upper, outcome = 0, 0, "failure"
            elif None in criteria:
                lower, upper, outcome = 0, 1, "unknown"
            else:
                lower, upper, outcome = 1, 1, "model_claimed_success"
            refs = len(packet["references"])
            if state == "supported":
                cite_bounds = (1, 1)
            elif state == "unsupported" and refs:
                bad = len(cite["review"]["bad_reference_indices"])
                cite_bounds = (0, (refs - bad) / refs)
            else:
                cite_bounds = (0, 1)
            rows.append({**item, "blind_id": blind, "strict_outcome": outcome, "strict_bounds": [lower, upper],
                "citation_accuracy_bounds": list(cite_bounds), "citation_count": refs,
                "question_requirements": len(packet["gold_points"]), "valid_model_satisfied_requirements": satisfied,
                "unknown_criteria": criteria.count(None), "citation_state": state})
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["category"], row["arm"]].append(row)
        summaries = []
        for (category, arm), group in sorted(grouped.items()):
            families = defaultdict(list)
            for row in group:
                families[row["family_id"]].append(row)
            summaries.append({"category": category, "arm": arm, "sessions": len(group), "families": len(families),
                "strict_outcome_counts": dict(Counter(r["strict_outcome"] for r in group)),
                "strict_question_repeat_rate_bounds": [statistics.mean(r["strict_bounds"][i] for r in group) for i in (0, 1)],
                "strict_family_macro_rate_bounds": [statistics.mean(statistics.mean(r["strict_bounds"][i] for r in values) for values in families.values()) for i in (0, 1)],
                "citation_family_macro_bounds": [statistics.mean(statistics.mean(r["citation_accuracy_bounds"][i] for r in values) for values in families.values()) for i in (0, 1)],
                "answer_structure_failures": sum(r["answer_structure"] != "complete_structure" for r in group)})
        def paired(arm, metric):
            families = defaultdict(list)
            for row in rows:
                if row["category"] == "cross" and row["arm"] == arm:
                    families[row["family_id"]].append(tuple(row[metric]))
            return dict(families)
        strict_ci = bounded_paired_bootstrap(paired("full", "strict_bounds"), paired("no_cross", "strict_bounds"), resamples=10000, seed=protocol["seed"])
        cite_ci = bounded_paired_bootstrap(paired("full", "citation_accuracy_bounds"), paired("no_cross", "citation_accuracy_bounds"), resamples=10000, seed=protocol["seed"])
        output.update(rows=rows, summary=summaries, judgment_status_counts=dict(statuses), strict_comparison=strict_ci,
            citation_comparison=cite_ci, citation_noninferiority_supported=cite_ci["bootstrap_envelope95"][0] > -.02,
            artifact_sha256=record_hashes, model_scored_sessions=len(rows),
            limits="same8B provisional semantic labels, not realhuman truth; unknowns retained and bounded; citation bounds are per-answer averages, non-exhaustive unsupported audits never make unlistedrefs good; human48sample separate")
    else:
        counters, records, unknown = defaultdict(Counter), {}, []
        for role, directory, names in (("shared_planner", root / "planner", {"plan.json"}),
            ("answer", root / "answers", {"draft.json", "final.json"}),
            ("pointwise_scoring", root / "evaluation_only/reviews", {"review.json"}),
            ("necessary_adjudication", root / "evaluation_only/adjudications", {"review.json"})):
            for file in sorted(directory.rglob("*.json")):
                if file.name not in names:
                    continue
                value = load(file)
                if value["request"]["model"] != protocol["model"] or value["request"]["temperature"] != 0 or value["request"].get("enable_thinking") is not False:
                    raise ValueError("formal request model/config drift")
                c = counters[role]
                c["requests"] += 1
                c["attempts"] += len(value.get("events", []))
                for event in value.get("events", []):
                    usage = event.get("usage")
                    c["seconds"] += event.get("seconds") or 0
                    c["attempt:" + event["status"]] += 1
                    if usage:
                        c["input_tokens"] += usage.get("prompt_tokens", 0)
                        c["output_tokens"] += usage.get("completion_tokens", 0)
                    else:
                        c["unknown_usage_attempts"] += 1
                        unknown.append({"path": str(file.relative_to(root)), "status": event["status"]})
                if value.get("status") == "response":
                    if value["raw_response"].get("model") != protocol["model"]:
                        raise ValueError("formal response model identity mismatch")
                    c["identity_verified_responses"] += 1
                records[str(file.relative_to(root))] = sha(file)
        price = load(protocol["public_inputs"]["price_basis"]["path"])
        by_role = {role: {**dict(c), "reported_public_list_cost_lowerbound_cny":
            c["input_tokens"] / 1e6 * price["input_cny_per_million_tokens"] + c["output_tokens"] / 1e6 * price["output_cny_per_million_tokens"]} for role, c in counters.items()}
        output.update(by_role=by_role, request_artifact_sha256=records, unknown_usage_attempts=unknown,
            estimated_public_list_cost_lowerbound_cny=sum(v["reported_public_list_cost_lowerbound_cny"] for v in by_role.values()),
            price_url=price["url"], limits="reportedresponse usage only, unknownattempts not zero; public Beijing listprice not accountbill; sharedplanning cost separate, no allocator doublecount; offlineconstruction inherited costs separate")
    save(args.output, output)
    print(json.dumps({"stage": args.stage, "status": "derived", "output": str(args.output), "new_llm_calls": 0}))


if __name__ == "__main__":
    main()
