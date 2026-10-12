"""用户授权的正式执行并发修订；使用原冻结提示词、验证器与传输恢复规则。"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError


class SharedRateWindow:
    """线程共享请求窗口；只保存请求摘要/资源预约，不保存凭据或检索内容。"""
    def __init__(self, file, rpm, tpm):
        self.file = file
        self.rpm, self.tpm = rpm, tpm
        self.lock = threading.Lock()
        self.entries = json.loads(file.read_text()) if file.exists() else []
        self.cooldown = 0
        self.rate_errors = 0
        self.wait_seconds = 0

    def flush(self):
        temp = self.file.with_suffix(".tmp")
        temp.write_text(json.dumps(self.entries) + "\n")
        temp.replace(self.file)

    def reserve(self, body):
        # 先按字符数+输出上限保守预约，收到响应后用真实usage释放多余预约。
        estimate = sum(len(m.get("content", "")) for m in body["messages"]) + body["max_tokens"]
        if estimate > self.tpm:
            raise ValueError("single-request resource estimate exceeds execution window")
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        started = time.monotonic()
        while True:
            with self.lock:
                now = time.time()
                self.entries = [e for e in self.entries if now - e["unix_seconds"] < 60]
                if now >= self.cooldown and len(self.entries) < self.rpm and sum(e["tokens"] for e in self.entries) + estimate <= self.tpm:
                    entry = {"unix_seconds": now, "request_sha256": digest, "tokens": estimate, "status": "reserved"}
                    self.entries.append(entry)
                    self.wait_seconds += time.monotonic()-started
                    self.flush()
                    return entry
            time.sleep(.2)

    def finish(self, entry, raw):
        with self.lock:
            try:
                usage = json.loads(raw).get("usage", {})
                actual = usage.get("total_tokens")
                if type(actual) is int and actual >= 0:
                    entry["tokens"] = actual
                    entry["status"] = "observed_usage"
            except (ValueError, TypeError, AttributeError):
                entry["status"] = "response_usage_unknown"
            self.flush()

    def error(self, entry, error):
        with self.lock:
            entry["status"] = "attempt_usage_unknown"
            if getattr(error, "code", None) == 429:
                self.rate_errors += 1
                self.cooldown = max(self.cooldown, time.time() + min(32, 2**min(self.rate_errors, 5)))
            self.flush()

    def wrap(self, original):
        limiter = self
        class Response:
            def __init__(self, response, entry):
                self.response, self.entry = response, entry
            def __enter__(self):
                self.response.__enter__()
                return self
            def __exit__(self, *args):
                return self.response.__exit__(*args)
            def read(self):
                raw = self.response.read()
                limiter.finish(self.entry, raw)
                return raw
        def open_request(request, **kwargs):
            body = json.loads(request.data)
            entry = limiter.reserve(body)
            try:
                return Response(original(request, **kwargs), entry)
            except BaseException as error:
                limiter.error(entry, error)
                raise
        return open_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--amendment", type=Path, required=True)
    parser.add_argument("--settings-file", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--stage", choices=("controller", "planner", "answer", "review", "adjudication"), default="controller")
    args = parser.parse_args()
    root, amendment = args.root.resolve(), args.amendment.resolve()
    sys.path.insert(0, str(root / "runtime"))
    from chapter2_formal_runtime import verify, load, save, sha, jobs, compiled, existing, ANSWER_ARMS, SELF_ARMS, BASE_ARMS
    protocol, protocol_sha = verify(root, require_snapshot=False)
    config_file = amendment / "execution_config.json"
    config = load(config_file)
    seal = load(amendment / "seal.json")
    if sha(config_file) != seal["execution_config_sha256"] or sha(Path(__file__)) != config["driver_sha256"] or config["original_protocol_sha256"] != protocol_sha:
        raise ValueError("execution amendment/source/original protocol drift")
    if args.stage in {"planner", "answer"} or args.preflight:
        from chapter2_production_guard import install
        install(offline=False, allow_test_public=True)
    import navigation_qa as qa
    import graphify_qa as net
    sys.path.insert(0, str(amendment))
    from chapter2_qwen_proxy_config import configure_qa, read_settings, install_provenance
    from chapter2_common_planner import compile_plan
    from chapter2_cited_answer import validate, answer_text, verification_feedback
    from chapter2_pointwise_review import validate as review_validate
    configure_qa(qa, args.settings_file, config["base_url"])
    if sha(amendment / "chapter2_qwen_proxy_config.py") != config["proxy_adapter_sha256"]:
        raise ValueError("sealed proxy adapter drift")
    install_provenance(net, qa, root, amendment, sha(config_file))
    net.SECRET = None if args.preflight or args.stage == "controller" else read_settings(args.settings_file)
    net.reset_transport_circuit()
    count_lock = threading.Lock()
    counts = Counter()
    lockpath = root / "locks" / ("controller.lock" if args.stage == "controller" and not args.preflight else "parallel--" + ("preflight" if args.preflight else args.stage) + ".lock")
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    with lockpath.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempt = amendment / "attempts" / str(time.time_ns())
        attempt.mkdir(parents=True)
        limiter = SharedRateWindow(amendment / "shared_rate_window.json", config["request_window_rpm"], config["token_window_tpm"])
        net.urlopen = limiter.wrap(net.urlopen)
        def mark(kind, key, status):
            with count_lock:
                counts[kind + ":" + status] += 1
            print("DONE", kind, key, status, flush=True)
        def plan_job(entry):
            key, repeat, question = entry
            folder = root / "planner" / key
            output = folder / "compiled.json"
            if existing(output, protocol_sha):
                compiled(root, key, question, protocol_sha)
                mark("planner", key, "reused")
                return
            request = qa.request([{"role": "system", "content": protocol["prompts"]["planner"]},
                {"role": "user", "content": qa.wire({"question": question["question"]})}], final=False)
            response = net.fetch(folder, "plan", request, net.SECRET)
            try:
                choice = qa.choice(response)
                if choice["finish_reason"] != "stop":
                    raise ValueError("planning response truncated")
                plan = compile_plan(qa.decode_json_prefix(choice["message"]["content"]), question["question"])
                value = {"status": "valid_structure", "plan": plan}
            except (ValueError, TypeError, KeyError) as error:
                value = {"status": "invalid_structure", "error": str(error), "plan": {"translation": "", "needs": [], "identifiers": []}}
            save(output, {**value, "question": question, "repeat": repeat, "response_sha256": sha(folder / "plan.json"),
                "artifact_sha256": {"plan.json": sha(folder / "plan.json")}, "protocol_sha256": protocol_sha,
                "execution_amendment_sha256": sha(config_file)})
            mark("planner", key, value["status"])
        def answer_job(entry):
            arm, (key, repeat, question) = entry
            folder = root / "answers" / arm / key
            output = folder / "compiled.json"
            if existing(output, protocol_sha):
                mark("answer", arm + "--" + key, "reused")
                return
            native_file = root / "native" / arm / (key + ".json")
            packet = load(native_file)
            plan, plan_sha = compiled(root, key, question, protocol_sha)
            if packet["question"] != question or packet["planner_compiled_sha256"] != plan_sha or packet["protocol_sha256"] != protocol_sha:
                raise ValueError("answer native provenance drift")
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
            messages += [{"role": "assistant", "content": draft_text},
                {"role": "user", "content": protocol["prompts"]["verify"] + "\n程序坐标检查：" + feedback}]
            final = net.fetch(folder, "final", qa.request(messages, final=True), net.SECRET)
            try:
                choice = qa.choice(final)
                if choice["finish_reason"] != "stop":
                    raise ValueError("final response truncated")
                value = validate(qa.decode_json_prefix(choice["message"]["content"]), delivery)
                result = {"status": "complete_structure", "answer": value, "answer_text": answer_text(value, delivery)}
            except (ValueError, TypeError, KeyError) as error:
                result = {"status": "incomplete", "answer": None, "answer_text": None, "error": str(error)}
            save(output, {**result, "question": question, "repeat": repeat, "arm": arm,
                "native_response_sha256": sha(native_file), "protocol_sha256": protocol_sha,
                "actual_source_feedback_characters": actual_chars, "answer_seconds": time.monotonic() - begin,
                "artifact_sha256": {name + ".json": sha(folder / (name + ".json")) for name in ("draft", "final")},
                "execution_amendment_sha256": sha(config_file)})
            mark("answer", arm + "--" + key, result["status"])
        def review_job(entry):
            key, job, adjudicate = entry
            file = root / "evaluation_only/review_packets" / (key + ".json")
            if sha(file) != job["packet_sha256"]:
                raise ValueError("blind scoring packet drift")
            packet = load(file)
            if adjudicate:
                first = load(root / "evaluation_only/reviews" / key / "compiled.json")
                if first["status"] == "valid_structure" and not (job["kind"] == "citations" and first["review"]["state"] == "uncertain"):
                    return
            folder = root / "evaluation_only" / ("adjudications" if adjudicate else "reviews") / key
            output = folder / "compiled.json"
            if output.exists():
                old = load(output)
                if old["protocol_sha256"] != protocol_sha or old["packet_sha256"] != job["packet_sha256"] or old["response_sha256"] != sha(folder / "review.json"):
                    raise ValueError("existing score drift")
                mark("adjudication" if adjudicate else "review", key, "reused")
                return
            prompt = protocol["prompts"]["point" if job["kind"] == "point" else "citations"]
            if adjudicate:
                prompt += "\n这是预注册的一次必要裁决。此前输出结构无效或支持性无法确定；请独立核验原材料并严格遵守字段与枚举。不改变实际回答，不补写事实，材料仍不足时保留不确定。"
            response = net.fetch(folder, "review", qa.request([{"role": "system", "content": prompt},
                {"role": "user", "content": qa.wire(packet)}], final=False), net.SECRET)
            try:
                choice = qa.choice(response)
                if choice["finish_reason"] != "stop":
                    raise ValueError("review response truncated")
                value = review_validate(qa.decode_json_prefix(choice["message"]["content"]), packet, job["kind"])
                result = {"status": "valid_structure", "review": value}
            except (ValueError, KeyError, TypeError) as error:
                result = {"status": "invalid_structure", "review": None, "error": str(error)}
            save(output, {**result, "packet_sha256": job["packet_sha256"], "response_sha256": sha(folder / "review.json"),
                "protocol_sha256": protocol_sha, "adjudication": adjudicate, "execution_amendment_sha256": sha(config_file)})
            mark("adjudication" if adjudicate else "review", key, result["status"])
        def online(stage, entries, worker):
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=config["online_workers"]) as pool:
                list(pool.map(worker, entries))
            save(attempt / (stage + ".json"), {"status": "complete", "seconds": time.monotonic()-started,
                "protocol_sha256": protocol_sha, "execution_amendment_sha256": sha(config_file)})
        def finish(name, count):
            file = root / "completion" / (name + ".json")
            if not file.exists():
                save(file, {"status": "complete", "jobs": count, "protocol_sha256": protocol_sha,
                    "execution_amendment_sha256": sha(config_file)})
        if args.preflight:
            # 非正式开发夹具：删除的compiled由既有响应恢复；key=None使任何缺响应立即报错。
            entries = list(jobs(protocol))
            online("planner", entries, plan_job)
            online("answer", [(arm, e) for e in entries for arm in ("full", "no_cross")], answer_job)
            save(attempt / "preflight.json", {"new_model_calls": 0, "counts": dict(counts), "limits": "development-only fixture, no formal quality"})
            return
        entries = list(jobs(protocol))
        if args.stage == "planner":
            online("planner", entries, plan_job)
            finish("planner--shared", len(entries))
            save(attempt / "summary.json", {"counts": dict(counts), "pacing_wait_seconds": limiter.wait_seconds,
                "rate_limit_errors": limiter.rate_errors, "execution_amendment_sha256": sha(config_file)})
            return
        if args.stage == "answer":
            rng = random.Random(protocol["seed"])
            answer_entries = []
            for e in entries:
                arms = list(ANSWER_ARMS)
                rng.shuffle(arms)
                answer_entries.extend((arm, e) for arm in arms)
            online("answer", answer_entries, answer_job)
            for arm in ANSWER_ARMS:
                finish("answer--" + arm, len(entries))
            save(attempt / "summary.json", {"counts": dict(counts), "pacing_wait_seconds": limiter.wait_seconds,
                "rate_limit_errors": limiter.rate_errors, "execution_amendment_sha256": sha(config_file)})
            return
        if args.stage in {"review", "adjudication"}:
            manifest = load(root / "evaluation_only/review_jobs.json")
            prepared = load(root / "completion/review_prepare.json")
            if prepared["review_jobs_sha256"] != sha(root / "evaluation_only/review_jobs.json") or manifest["identity_sha256"] != sha(root / "evaluation_only/identity.json"):
                raise ValueError("prepared blind manifest drift")
            online(args.stage, [(key, job, args.stage == "adjudication") for key, job in manifest["jobs"].items()], review_job)
            for shard in range(protocol["scoring_shards"]):
                finish(args.stage + "--" + str(shard), sum(i % protocol["scoring_shards"] == shard for i in range(len(manifest["jobs"]))))
            save(attempt / "summary.json", {"counts": dict(counts), "pacing_wait_seconds": limiter.wait_seconds,
                "rate_limit_errors": limiter.rate_errors, "execution_amendment_sha256": sha(config_file)})
            return
        def online_process(stage):
            file = attempt / (stage + ".log")
            with file.open("x") as stream:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                    "--amendment", str(amendment), "--settings-file", str(args.settings_file.resolve()),
                    "--stage", stage], stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError("parallel online process stopped: " + stage)
            print("STAGE", stage, "complete", flush=True)
        online_process("planner")
        rng = random.Random(protocol["seed"])
        arms = list(SELF_ARMS) + list(BASE_ARMS)
        rng.shuffle(arms)
        def native(arm):
            file = attempt / ("native--" + arm + ".log")
            with file.open("x") as stream:
                result = subprocess.run([sys.executable, str(root / "runtime/chapter2_formal_runtime.py"), "native",
                    "--root", str(root), "--arm", arm], stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError("frozen native process stopped: " + arm)
            print("STAGE native", arm, "complete", flush=True)
        with ThreadPoolExecutor(max_workers=protocol["recovery"]["concurrency"]) as pool:
            list(pool.map(native, arms))
        online_process("answer")
        from chapter2_formal_review import prepare
        if not (root / "completion/review_prepare.json").exists():
            prepare(root, protocol, protocol_sha)
        for stage in ("review", "adjudication"):
            online_process(stage)
        save(attempt / "summary.json", {"counts": dict(counts), "pacing_wait_seconds": limiter.wait_seconds,
            "rate_limit_errors": limiter.rate_errors, "execution_amendment_sha256": sha(config_file), "protocol_sha256": protocol_sha})
        finish("controller", protocol["planned_sessions"])


if __name__ == "__main__":
    main()
