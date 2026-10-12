"""仅根据已完成开发记录冻结正式实现、协议与预算；冻结前不读测试问题。"""
import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys

from chapter2_formal_runtime import sha, load, save, ANSWER_ARMS, SELF_ARMS, BASE_ARMS
from chapter2_common_planner import PROMPT
from chapter2_cited_answer import DRAFT_PROMPT, VERIFY_PROMPT
from chapter2_pointwise_review import POINT, CITATIONS
from chapter2_graph_retriever import DEFAULTS

NAMES = ("chapter2_formal_runtime.py", "chapter2_formal_review.py", "chapter2_formal_freeze.py", "chapter2_formal_controller.py",
    "chapter2_common_planner.py", "chapter2_cited_answer.py", "chapter2_pointwise_review.py",
    "chapter2_graph_retriever.py", "chapter2_baseline_native.py", "chapter2_canonical_delivery.py",
    "canonical_evidence_v1.py", "chapter2_aliyun_config.py", "chapter2_production_guard.py",
    "navigation_qa.py", "graphify_qa.py", "graphify_query_backend.py", "candidate_graph_utils.py",
    "candidate_paths.py", "index_free_graph_evidence.py", "candidate_hybrid.py",
    "chapter2_native_dev_score.py", "chapter2_family_statistics.py", "chapter2_role_graph.py")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("PYTHONHASHSEED=0 required")
    archive = args.archive.resolve()
    dataset = archive / "datasets/frozen_001"
    manifest = load(dataset / "manifest.json")
    summary = load(archive / "dev/round_03_summary_001.json")
    if summary["status"] != "complete" or manifest["test"]["questions"] != 96:
        raise ValueError("completed D3 and frozen96-question dataset required")
    if args.output.exists():
        raise FileExistsError("new formal version required")
    source = Path(__file__).parent
    runtime = args.output / "runtime"
    runtime.mkdir(parents=True)
    for name in NAMES:
        shutil.copy2(source / name, runtime / name)
    smoke = archive / "dev/smoke_001"
    inputs = {
        "dataset_manifest": dataset / "manifest.json", "corpus_manifest": dataset / "corpus-manifest.json",
        "self_graph": archive / "graphs/round_03/principia-graph.json",
        "self_construction_manifest": archive / "graphs/round_03/construction-manifest.json",
        "graphify_native_graph": smoke / "native/graphify-out/graph.json",
        "graphify_text_adapter_graph": smoke / "text_adapter/graphify-out/graph.json",
        "graphify_path_map": smoke / "text_adapter/path-map.json",
        "e5_index_manifest": smoke / "vector-index/manifest.json", "e5_passages": smoke / "vector-index/passages.json",
        "e5_embeddings": smoke / "vector-index/embeddings.npy",
        "development_closure": archive / "dev/round_03_summary_001.json",
        "price_basis": archive / "audit/aliyun_qwen3_8b_public_price_001.json",
        "runtime_preflight": archive / "audit/formal_runtime_preflight_001.json",
        "offline_model_audit": archive / "audit/offline_model_configuration_001.json",
        "inherited_self_semantic_protocol004": archive.parent / "self_graph_v2/semantics/004/protocol.json",
        "inherited_self_semantic_protocol005": archive.parent / "self_graph_v2/semantics/005/protocol.json",
        "inherited_graphify_native_construction": archive.parent / "graphify_flash_v2/native/baseline_summary.json",
        "inherited_graphify_text_construction": archive.parent / "graphify_flash_v2/text_adapter/baseline_summary.json"}
    public = {name: {"path": str(file), "sha256": sha(file)} for name, file in inputs.items()}
    # 直接复制C阶段已冻结哈希；本过程不读取问题/gold字节。
    public["questions"] = {"path": str(dataset / "public_test/questions.json"), "sha256": manifest["artifacts"]["public_test/questions.json"]}
    upstream = archive.parent / "graphify_flash_v2/upstream"
    for file in sorted((upstream / "graphify").rglob("*.py")):
        public["upstream:" + str(file.relative_to(upstream))] = {"path": str(file), "sha256": sha(file)}
    index_manifest = load(inputs["e5_index_manifest"])
    from candidate_hybrid import local_snapshot
    snapshot = local_snapshot(index_manifest["model"])
    for file in sorted(snapshot.rglob("*")):
        if file.is_file():
            public["e5_model:" + str(file.relative_to(snapshot))] = {"path": str(file), "sha256": sha(file)}
    packages = {}
    for name in ("numpy", "networkx", "torch", "sentence-transformers", "transformers", "huggingface-hub", "safetensors"):
        packages[name] = importlib.metadata.version(name)
    # 时间估算仅取已完成开发响应，不访问正式题目。
    role_dirs = {"planner": archive / "dev/round_03_common_planner_001",
        "answer": archive / "dev/round_03_cited_answer_001",
        "pointwise": archive / "dev/evaluation_only/round_03_pointwise_review_001"}
    observed = {}
    for role, directory in role_dirs.items():
        response_records = []
        for file in (directory / "responses").rglob("*.json"):
            value = load(file)
            if value.get("status") == "response" and "raw_response" in value:
                response_records.append(value)
        usage = [v["raw_response"].get("usage", {}) for v in response_records]
        observed[role] = {"response_count": len(response_records),
            "input_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
            "output_tokens": sum(u.get("completion_tokens", 0) for u in usage),
            "response_seconds": sum(e.get("seconds") or 0 for v in response_records for e in v.get("events", []))}
    expected_calls = {"planner": 288, "answer": 3456, "pointwise": round(1728 * observed["pointwise"]["response_count"] / 24)}
    estimated_in = sum(expected_calls[r] * o["input_tokens"] / o["response_count"] for r, o in observed.items())
    estimated_out = sum(expected_calls[r] * o["output_tokens"] / o["response_count"] for r, o in observed.items())
    seconds = sum(expected_calls[r] * o["response_seconds"] / o["response_count"] for r, o in observed.items())
    price = load(inputs["price_basis"])
    budget = {"observed_development": observed, "expected_base_calls": expected_calls,
        "expected_input_tokens": estimated_in, "expected_output_tokens": estimated_out,
        "estimated_public_list_cost_cny": estimated_in / 1e6 * price["input_cny_per_million_tokens"] + estimated_out / 1e6 * price["output_cny_per_million_tokens"],
        "estimated_sequential_response_hours": seconds / 3600, "estimated_ideal_three_worker_response_hours": seconds / 10800, "concurrency": 3,
        "adjudication_reserve": "one extra call per invalid point/citation or uncertain citation, worst-case additional pointwise base count; no answer regeneration",
        "price_url": price["url"], "price_region_basis": price["region_basis"],
        "limits": "development-average estimate, not spending cap or account bill; test point count/source lengths/transport latency differ; no formal denominator reduced by observed quality or spend"}
    save(args.output / "resource_budget.json", budget)
    n = 27
    minimum = next(k for k in range(n+1) if (1-k/n)**n < .025)
    power = sum(math.comb(n, k) * .08**k * .92**(n-k) for k in range(minimum, n+1))
    save(args.output / "detection_capacity.json", {"independent_cross_families": n,
        "illustration": "one-sided benefit-only Bernoulli family differences 0/1; bootstrap lower2.5 percentile positive iff zero-benefit resample probability <.025",
        "minimum_benefiting_families_in_illustration": minimum, "illustrative_detection_probability_at_8pp": power,
        "limits": "illustration assumes no harmed families, binary whole-family gain; real9-observation family means and heterogeneity differ; not a guarantee or general power calculation"})
    protocol = {"schema": "aliyun8b-formal-cross-source-frozen-v1", "frozen": True, "date": "2026-10-03",
        "development_major_rounds_completed": 3, "further_method_tuning_allowed": False,
        "model": "qwen3-8b", "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "offline_construction": {"semantic_model": "deepseek-flash", "new_graph_llm_calls": 0,
            "provider_endpoint": "https://api.deepseek.com/chat/completions",
            "self_semantic_generation": {"temperature": 0, "thinking": {"type": "disabled"}, "max_tokens": 8000, "response_format": {"type": "json_object"}},
            "graphify_generation": "temperature0,streamfalse; max_completion_tokens448/3136/5056/16384 per retained request; provider thinking default not overridden; full counts in frozen offline_model_audit",
            "enhancement": "deterministic public role graph, inherited frozen flash semantic base; complete inherited cold-build cost unavailable",
            "construction_manifest_sha256": public["self_construction_manifest"]["sha256"]},
        "generation": {"temperature": 0, "enable_thinking": False, "response_format": {"type": "json_object"},
            "planner_max_tokens": 700, "answer_max_tokens_per_stage": 2400, "scoring_max_tokens": 700},
        "prompts": {"planner": PROMPT, "draft": DRAFT_PROMPT, "verify": VERIFY_PROMPT, "point": POINT, "citations": CITATIONS},
        "repeats": 3, "seed": 20261003, "scoring_shards": 3, "answer_arms": list(ANSWER_ARMS),
        "native_arms": list(SELF_ARMS) + list(BASE_ARMS), "self_ablation_options": SELF_ARMS, "self_defaults": DEFAULTS,
        "planned_sessions": 1728, "planned_native_queries": 2592, "planned_common_planner_calls": 288,
        "query_policy": "one fresh public8B plan per question/repeat shared identically by9 backends; unchanged public question retained; invalid plan raw-question fallback, no quality resampling",
        "repetition_limits": "temperature0 fresh requests are repeated executions, not independent facts; question variants and repeats pooled within family",
        "native_limit": 64, "budgets": [6000, 12000, 24000], "primary_budget": 24000,
        "return_character_cap": 24000, "source_character_cap": 23488, "feedback_character_reserve": 512,
        "answer_workflow": "same source-only context, one draft, deterministic coordinate feedback, one final correction; no extra retrieval; final schema failure scored as answer failure",
        "baseline_differences": {"no_graph": "query-local BM25 original-source passages, no persistent index; stronger raw-text baseline than historical adaptive line-search control",
            "graphify": "fixed upstream native seeds/BFS/order before authoritative mapping; text adapter byte-preserving paths restored; absent location falls back to whole source with explicit weak mapping; images/binary remain unmap rank penalties",
            "e5": "independent pure dense cosine top64, multilingual-e5-small revision614241f622f53c4eeff9890bdc4f31cfecc418b3, maxseq512 CPUthreads4; no hybrid BM25/postings/graph; framework preload separate",
            "self": "only graph+necessary corpus hashes; graph field scans, derived adjacency and query-local source reuse; no external index or cross-query token/source cache"},
        "scoring": {"method_blind": True, "requirement_grading": "one pointwise call per frozen gold requirement plus whole citation audit; no self-selected scoring points",
            "strict_success": "answer structure valid AND all requirements satisfied+supported AND whole citation audit supported without extra errors",
            "necessary_adjudication": "exactly one independent same8B call only when first structure invalid or whole citation state uncertain; same unchanged material and prompt+frozen clarification; no negative/poor-answer resampling",
            "remaining_unknown": "null retained; known failure criterion dominates other unknowns; otherwise success bounds[0,1]; report both bounds and pessimistic/optimistic family paired bootstrap envelope",
            "citation_accuracy": "supported whole audit verifies all claimed references; unsupported identifies bad indices only, others remain unknown; uncertain/invalid all unknown; report bounds, do not impute unlisted refs good",
            "human_disagreement": "retain original8B labels; publish separate real-human corrections for sampled sessions, one same8B adjudication allowed with human stated issue; no extrapolation to unsampled answers"},
        "metrics": {"primary": "cross-only all necessary evidence atoms and sources fully covered by actual24000-character delivery",
            "auxiliary": "Recall@1/3/5/10, Complete@5/10,MRR,nDCG@10 observed candidate-pool reranking diagnostic, necessary-gold precision lower bound,atom recall,actual23488 answer evidence completeness,strict answer bounds,citation bounds,scope associations,costs",
            "canonical": "canonical_evidence_v1 original path/hash/lines/source/scope/native rank/dedup rank/cumulativeactualchars; unmappable placeholders retain rank+metadata budget, are never citable",
            "ndcg_limits": "observed necessary-gold candidate pool ideal, not exhaustive relevance; legacy gold-count denominator retained only audit",
            "aggregation": "question/repeat means and family macro; independent27crossfamilies,4manual,1tutorial separate",
            "scope_error": "deterministic wrong-case association proxy: delivered tutorial units with case_directory outside frozen family cases / delivered tutorial units with identified case; manual-only family tutorial units separately wrong-source; not exhaustive dictionary-role semantic error, sample route/citation audits provide role/condition analysis",
            "ablation_checks": "no_cross every used route has no cross-source step; node_scan every route empty; no_scope option disabled explicitly; fixedwindow branch uses same rank graph and radius8 insteadof structural owner reads"},
        "statistics": {"paired_bootstrap_samples": 10000, "seed": 20261003, "ci": .95,
            "unit": "family; all3variants x3repeats averaged within family before pairing",
            "primary_comparison": "full minus no_cross cross complete evidence @24000",
            "mechanism_supported": "paired95%CI lower>0 and pointdifference>0", "practical_target_pp": 8,
            "citation_noninferiority_margin_pp": 2,
            "citation_rule": "full-no_cross paired lower95%CI > -0.02; unknowns use worst-case bound envelope; otherwise no noninferiority claim",
            "secondary_comparisons": "other ablations and six-system rankings descriptive/exploratory, no claim of multiplicity-corrected superiority"},
        "human_review": {"sessions": 48, "proportion": 48/1728, "families_by_category": {"cross": 5, "manual": 2, "tutorial": 1},
            "selection": "seed20261003 shuffle sorted families independently by category; take5/2/1, choose variant1-3+repeat1-3 with same RNG, includeall6arms; blind packets reshuffled; independent of outcome",
            "instructions": "真实人工逐项评价gold要求的事实完整正确性、自己的引用是否支持、角色/条件错误。填写human_verdict pass/fail/uncertain及具体理由；不能把AI或作者自动审计称人工复核。",
            "handling": "report agreement, model falsepositive/falsenegative and invalid rates; preserve original model dataset and separate sampled-human corrections; no whole-grid extrapolation"},
        "recovery": {"concurrency": 3, "lock": "exclusive stage/arm process lock and fixed job-index modulo3 scoring shards; no parallel writer per request",
            "scheduling": "seeded native-arm/answer-arm launch shuffle, three independent workers per stage; shared planning first; allanswers barrier before scoring; provider wall-time differences disclosed",
            "transport": "frozen graphify_qa.fetch identicalrequest max3attempts/process and max9total; interrupted usage unknown retained; received invalid response terminal; circuit after4 transport outages",
            "structure": "no planner/answer regeneration; invalid planner raw fallback, final invalid answer failure; scoring only one adjudication as registered",
            "resume": "verify allfrozen hashes; reuse verified completed exactsame request/response only; no output overwrite except append transport attempts within frozen fetch",
            "unresolved_transport": "preserve missing slots and full denominator; report unknowns/bounds and incomplete grid, never claim allgrid completed; quota outage pause externalcalls while finish offlinework",
            "implementation_errata": "halt affected stage, bind issue/inputhashes, preserve originals; format/source mapping correction only with pre-result-independent rationale and new version; new method tuning requires new independentdataset"},
        "environment": {"python": sys.version, "platform": platform.platform(), "packages": packages, "python_hash_seed": "0"},
        "paths": {"corpus": str(archive.parent / "graphify_flash_v2/corpus_native"), "graphify_upstream": str(upstream), "e5_index": str(smoke / "vector-index")},
        "public_inputs": public,
        "private_scoring_input": {"path": str(dataset / "evaluation_only/test.annotations.json"), "sha256": manifest["artifacts"]["evaluation_only/test.annotations.json"]},
        "runtime_sha256": {name: sha(runtime / name) for name in NAMES},
        "resource_budget_sha256": sha(args.output / "resource_budget.json"), "detection_capacity_sha256": sha(args.output / "detection_capacity.json"),
        "security": "key read from .env.aliyun only, never logged/hashed; productionPython audit guard denies all gold/data_design paths/subprocess and disables network in retrieval; not OS isolation",
        "historical_limits": "new fact combinations on previously seen corpus with old answer components; historicalheldout exposed and excluded; same8B answer/grader not independent; human48sampledoesnotprovealllabels",
        "future_model_sizes": {"14b": "not authorized/currentcompletionnotrequired", "32b": "not authorized/currentcompletionnotrequired"}}
    save(args.output / "protocol.json", protocol)
    save(args.output / "seal.json", {"schema": "formal-freeze-seal-v1", "protocol_sha256": sha(args.output / "protocol.json"),
        "before_formal_calls": True, "formal_calls_at_seal": 0})
    print(json.dumps({"protocol_sha256": sha(args.output / "protocol.json"), "sessions": 1728,
        "estimated_public_list_cost_cny": budget["estimated_public_list_cost_cny"], "estimated_response_hours": seconds/3600}, ensure_ascii=False))


if __name__ == "__main__":
    main()
