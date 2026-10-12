"""正式冻结运行器：生产阶段无gold，各后端独立进程，共享公开规划。"""
import argparse
import fcntl
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import sys
import time

SELF_ARMS = {"full": {}, "no_cross": {"with_cross": False}, "no_scope": {"with_scope": False},
             "fixed_window": {"structured_read": False}, "node_scan": {"with_paths": False}}
BASE_ARMS = ("no_graph", "graphify_native", "graphify_text_adapter", "e5")
ANSWER_ARMS = ("no_graph", "graphify_native", "graphify_text_adapter", "full", "e5", "no_cross")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL also prevents simultaneous workers from replacing completed artifacts.
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def verify(root, require_snapshot=True):
    root = root.resolve()
    seal = load(root / "seal.json")
    if sha(root / "protocol.json") != seal["protocol_sha256"]:
        raise ValueError("formal protocol drift")
    protocol = load(root / "protocol.json")
    if os.environ.get("PYTHONHASHSEED") != "0" or sys.version != protocol["environment"]["python"]:
        raise ValueError("frozen interpreter/PYTHONHASHSEED required")
    for relative, expected in protocol["runtime_sha256"].items():
        if sha(root / "runtime" / relative) != expected:
            raise ValueError("frozen runtime drift: " + relative)
    if require_snapshot and Path(__file__).resolve() != (root / "runtime" / Path(__file__).name).resolve():
        raise ValueError("execute formal runtime snapshot")
    for name, expected in protocol["environment"]["packages"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError("frozen package drift: " + name)
    for name in ("resource_budget", "detection_capacity"):
        if sha(root / (name + ".json")) != protocol[name + "_sha256"]:
            raise ValueError("frozen protocol attachment drift")
    for item in protocol["public_inputs"].values():
        if sha(item["path"]) != item["sha256"]:
            raise ValueError("frozen public input drift")
    return protocol, seal["protocol_sha256"]


def jobs(protocol):
    for repeat in range(1, protocol["repeats"] + 1):
        for question in load(protocol["public_inputs"]["questions"]["path"]):
            yield f"r{repeat}--{question['id']}", repeat, question


def compiled(root, key, question, protocol_sha):
    file = root / "planner" / key / "compiled.json"
    value = load(file)
    if value["question"] != question or value["protocol_sha256"] != protocol_sha or value["response_sha256"] != sha(file.parent / "plan.json"):
        raise ValueError("shared planner provenance drift")
    return value, sha(file)


def transport(settings):
    qa = importlib.import_module("navigation_qa")
    config = importlib.import_module("chapter2_aliyun_config")
    net = importlib.import_module("graphify_qa")
    config.configure_qa(qa)
    net.SECRET = config.read_settings(settings)
    net.reset_transport_circuit()
    return qa, net


def existing(file, protocol_sha):
    if not file.exists():
        return False
    value = load(file)
    if value["protocol_sha256"] != protocol_sha:
        raise ValueError("existing result protocol drift")
    if value.get("artifact_sha256"):
        for path, expected in value["artifact_sha256"].items():
            if sha(file.parent / path) != expected:
                raise ValueError("existing dependent artifact drift")
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("verify", "planner", "native", "answer"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--arm", choices=tuple(SELF_ARMS) + BASE_ARMS)
    p.add_argument("--settings-file", type=Path)
    args = p.parse_args()
    root = args.root.resolve()
    protocol, protocol_sha = verify(root)
    if args.stage == "verify":
        print(json.dumps({"status": "verified", "protocol_sha256": protocol_sha, "test_calls": 0}))
        return
    if args.stage in {"native", "answer"} and not args.arm:
        p.error("--arm required")
    if args.stage == "answer" and args.arm not in ANSWER_ARMS:
        p.error("retrieval-only ablation has no answer arm")
    # 独立E5框架预载在防护前；自研进程从不导入此分支。
    preload = time.monotonic()
    if args.stage == "native" and args.arm == "e5":
        os.environ["HF_HUB_OFFLINE"] = "1"
        import torch
        import sentence_transformers
    preload_seconds = time.monotonic() - preload
    if args.stage == "native" and args.arm in {"graphify_native", "graphify_text_adapter"}:
        sys.path.insert(0, protocol["paths"]["graphify_upstream"])
    from chapter2_production_guard import install
    guard = install(offline=args.stage == "native", allow_test_public=True)
    lockpath = root / "locks" / (args.stage + "--" + (args.arm or "shared") + ".lock")
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    with lockpath.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.monotonic()
        if args.stage in {"planner", "answer"}:
            qa, net = transport(args.settings_file)
        if args.stage == "native":
            corpus = Path(protocol["paths"]["corpus"])
            manifest = Path(protocol["public_inputs"]["corpus_manifest"]["path"])
            load_started = time.monotonic()
            if args.arm in SELF_ARMS:
                from chapter2_graph_retriever import GraphRetriever
                engine = GraphRetriever(protocol["public_inputs"]["self_graph"]["path"], corpus, SELF_ARMS[args.arm], manifest)
            else:
                from chapter2_baseline_native import NoGraphBM25, DenseE5, GraphifyNative
                if args.arm == "no_graph":
                    engine = NoGraphBM25(corpus, manifest)
                elif args.arm == "e5":
                    engine = DenseE5(corpus, manifest, Path(protocol["paths"]["e5_index"]))
                else:
                    graph = protocol["public_inputs"][args.arm + "_graph"]["path"]
                    path_map = protocol["public_inputs"]["graphify_path_map"]["path"] if args.arm == "graphify_text_adapter" else None
                    engine = GraphifyNative(corpus, manifest, Path(graph), Path(path_map) if path_map else None)
            load_seconds = time.monotonic() - load_started
            from chapter2_canonical_delivery import canonicalize, render
        count = 0
        for key, repeat, question in jobs(protocol):
            if question["split"] != "test":
                raise ValueError("formal test questions required")
            count += 1
            if args.stage == "planner":
                folder = root / "planner" / key
                output = folder / "compiled.json"
                if existing(output, protocol_sha):
                    compiled(root, key, question, protocol_sha)
                    continue
                from chapter2_common_planner import compile_plan
                response = net.fetch(folder, "plan", qa.request([
                    {"role": "system", "content": protocol["prompts"]["planner"]},
                    {"role": "user", "content": qa.wire({"question": question["question"]})}], final=False), net.SECRET)
                try:
                    choice = qa.choice(response)
                    if choice["finish_reason"] != "stop":
                        raise ValueError("planning response truncated")
                    plan = compile_plan(qa.decode_json_prefix(choice["message"]["content"]), question["question"])
                    value = {"status": "valid_structure", "plan": plan}
                except (ValueError, TypeError, KeyError) as error:
                    value = {"status": "invalid_structure", "error": str(error), "plan": {"translation": "", "needs": [], "identifiers": []}}
                save(output, {**value, "question": question, "repeat": repeat, "response_sha256": sha(folder / "plan.json"),
                              "artifact_sha256": {"plan.json": sha(folder / "plan.json")}, "protocol_sha256": protocol_sha})
            elif args.stage == "native":
                output = root / "native" / args.arm / (key + ".json")
                if existing(output, protocol_sha):
                    continue
                plan, plan_sha = compiled(root, key, question, protocol_sha)
                query_started = time.monotonic()
                if args.arm in SELF_ARMS:
                    native = engine.rank(question["question"], plan["plan"])
                    packet = engine.read_native(native)
                    seconds = time.monotonic() - query_started
                    diagnostic = {"seconds": seconds, "reading_seconds": packet["reading_seconds"]}
                else:
                    packet, diagnostic = engine.query(question["question"], plan["plan"], 64)
                    native = None
                    seconds = diagnostic["seconds"]
                units = canonicalize(packet, seconds)
                save(output, {"question": question, "repeat": repeat, "arm": args.arm, "native": native,
                    "mapped_native": packet, "canonical_units": units,
                    "deliveries": {str(b): render(units, b) for b in protocol["budgets"]},
                    "answer_delivery": render(units, protocol["source_character_cap"]),
                    "diagnostic": diagnostic, "query_seconds": seconds, "load_seconds": load_seconds,
                    "framework_preload_seconds": preload_seconds, "planner_compiled_sha256": plan_sha,
                    "guard": guard, "protocol_sha256": protocol_sha,
                    "resource": {"max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                 "process_cpu_seconds": time.process_time()}})
            else:
                folder = root / "answers" / args.arm / key
                output = folder / "compiled.json"
                if existing(output, protocol_sha):
                    continue
                native_file = root / "native" / args.arm / (key + ".json")
                packet = load(native_file)
                plan, plan_sha = compiled(root, key, question, protocol_sha)
                if packet["question"] != question or packet["planner_compiled_sha256"] != plan_sha or packet["protocol_sha256"] != protocol_sha:
                    raise ValueError("answer native provenance drift")
                from chapter2_cited_answer import validate, answer_text, verification_feedback
                delivery = packet["answer_delivery"]
                messages = [{"role": "system", "content": protocol["prompts"]["draft"]},
                    {"role": "user", "content": "公开问题：" + question["question"] + "\n权威原文：\n" + delivery["text"]}]
                begin = time.monotonic()
                draft = net.fetch(folder, "draft", qa.request(messages, final=True), net.SECRET)
                try:
                    draft_text = qa.choice(draft)["message"]["content"]
                except (ValueError, TypeError, KeyError):
                    draft_text = ""
                feedback = verification_feedback(draft, delivery, qa)
                actual_chars = len(delivery["text"]) + len(feedback) + len("程序坐标检查：")
                if actual_chars > protocol["return_character_cap"]:
                    raise ValueError("actual source plus feedback cap exceeded")
                messages += [{"role": "assistant", "content": draft_text}, {"role": "user", "content": protocol["prompts"]["verify"] + "\n程序坐标检查：" + feedback}]
                final = net.fetch(folder, "final", qa.request(messages, final=True), net.SECRET)
                try:
                    choice = qa.choice(final)
                    if choice["finish_reason"] != "stop":
                        raise ValueError("final response truncated")
                    value = validate(qa.decode_json_prefix(choice["message"]["content"]), delivery)
                    result = {"status": "complete_structure", "answer": value, "answer_text": answer_text(value, delivery)}
                except (ValueError, TypeError, KeyError) as error:
                    result = {"status": "incomplete", "answer": None, "answer_text": None, "error": str(error)}
                save(output, {**result, "question": question, "repeat": repeat, "arm": args.arm,
                    "native_response_sha256": sha(native_file), "protocol_sha256": protocol_sha,
                    "actual_source_feedback_characters": actual_chars, "answer_seconds": time.monotonic() - begin,
                    "artifact_sha256": {name + ".json": sha(folder / (name + ".json")) for name in ("draft", "final")}})
            print("DONE", args.stage, args.arm or "shared", key, flush=True)
        completion = root / "completion" / (args.stage + "--" + (args.arm or "shared") + ".json")
        if not completion.exists():
            save(completion, {"status": "complete", "jobs": count, "protocol_sha256": protocol_sha,
                "process_seconds": time.monotonic() - started, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})


if __name__ == "__main__":
    main()
