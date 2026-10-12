"""第2章基础agent＋单项检索增强。prepare/check/estimate不调用模型。"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import time
import urllib.error
import urllib.request

from chapter2_baseline_native import OriginalSources
from chapter2_canonical_delivery import canonicalize, render
from chapter2_cited_answer import validate

ARMS = ("grep", "grep_bm25", "grep_e5", "grep_graph")
ABLATIONS = {"full": {}, "no_cross": {"with_cross": False},
             "no_scope": {"with_scope": False}, "fixed_window": {"structured_read": False},
             "node_scan": {"with_paths": False}}
LIMITS = {"tool_calls": 8, "tool_characters": 6000, "new_evidence_characters": 24000,
          "request_input_tokens": 24000, "session_input_tokens": 120000,
          "answer_output_tokens": 2400, "judge_output_tokens": 4000,
          "final_context_headroom": 3072}
SYSTEM = """你是blastFoam资料检索agent，程序没有预先提供原文。每轮必须输出一个JSON行动。
检索行动：{"action":"tool","name":"grep","arguments":{"query":"关键词","path_glob":"*"}}。
最终行动：{"action":"final","answer":{"claims":[{"text":"事实","citations":[{"source":"S1","start":1,"end":2}]}],"unresolved":["证据缺口"]}}。
基础工具为grep、locate_files、read_source，另有工具时见下面的可用工具说明。自行选择工具、改写查询、核验和停止。
需要资料时先调用工具。只有工具返回的实际原文可以作为事实依据，引用S编号和行号也必须来自实际工具返回。
尚无原文时禁止生成claims或虚构引用；可以先检索，或用空claims和unresolved披露缺口。
区分教程静态声明、手册定义、默认值与条件，不能声称运行过仿真或条件已经满足。不要依据记忆补写。
一次只能调用一个工具，arguments必须匹配工具说明。仅输出行动JSON，不输出额外文字。"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def tools_for(arm):
    if arm not in ARMS:
        raise ValueError("unknown arm")
    def tool(name, description, properties, required):
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required,
                               "additionalProperties": False}}}
    text = {"type": "string"}
    result = [tool("grep", "在原文中查找不区分大小写的字面字符串，按路径/行顺序返回匹配及相邻行。",
                   {"query": text, "path_glob": text}, ["query"]),
              tool("locate_files", "按glob定位权威语料相对路径，按路径排序。", {"pattern": text}, ["pattern"]),
              tool("read_source", "读取权威原文指定完整行段。", {"path": text, "start": {"type": "integer", "minimum": 1},
                   "end": {"type": "integer", "minimum": 1}}, ["path", "start", "end"])]
    names = {"grep_bm25": "bm25_search", "grep_e5": "e5_search", "grep_graph": "graph_search"}
    if arm in names:
        label = {"grep_bm25": "BM25词项相关性", "grep_e5": "E5语义相似性", "grep_graph": "图节点匹配及受约束关系扩展"}[arm]
        result.append(tool(names[arm], f"用{label}检索权威语料，返回排序后的原文证据；可结合基础工具核验。",
                           {"query": text}, ["query"]))
    return result


class ToolSession:
    """仅读取公开manifest内原文。不同arm仅懒加载自己的增强后端。"""
    def __init__(self, protocol, arm, engine=None):
        self.protocol, self.arm = protocol, arm
        self.sources = OriginalSources(protocol["corpus"], protocol["inputs"]["corpus_manifest"]["path"])
        self.engine = engine
        self.units, self.events, self.seen = [], [], set()
        self.new_characters = 0

    def packet(self, ranges):
        items = []
        for i, (path, start, end) in enumerate(ranges, 1):
            items.append({"path": path, "start": start, "end": end,
                          "native_rank": i, "native_unit": f"{path}:{start}-{end}"})
        return self.sources.map(items)

    def invoke(self, name, args):
        specs = {t["function"]["name"]: t["function"]["parameters"] for t in tools_for(self.arm)}
        if name not in specs:
            raise ValueError("tool not enabled for this arm")
        spec = specs[name]
        if not isinstance(args, dict) or set(args) - set(spec["properties"]) or not set(spec["required"]) <= set(args):
            raise ValueError("invalid tool arguments")
        for key, value in args.items():
            if spec["properties"][key]["type"] == "string":
                if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                    raise ValueError("invalid string argument")
            elif type(value) is not int or value < 1:
                raise ValueError("invalid line number")
        if name == "locate_files":
            paths = [p for p in sorted(self.sources.hashes) if fnmatch.fnmatchcase(p, args["pattern"])]
            kept = []
            for path in paths:
                if len(wire({"paths": kept + [path], "truncated": True})) > LIMITS["tool_characters"]:
                    break
                kept.append(path)
            return wire({"paths": kept, "truncated": len(kept) < len(paths)}), None
        if name == "read_source":
            path = args["path"]
            lines = self.sources.read(path, {})
            if lines is None or not 1 <= args["start"] <= args["end"] <= len(lines):
                raise ValueError("path outside manifest or invalid original line range")
            return None, self.packet([(path, args["start"], args["end"])])
        if name == "grep":
            ranges = []
            for path in sorted(self.sources.hashes):
                if not fnmatch.fnmatchcase(path, args.get("path_glob", "*")):
                    continue
                lines = self.sources.read(path, {}) or []
                for i, line in enumerate(lines, 1):
                    if args["query"].casefold() in line.casefold():
                        ranges.append((path, max(1, i - 4), min(len(lines), i + 4)))
                        if len(ranges) == 64:
                            break
                if len(ranges) == 64:
                    break
            return None, self.packet(ranges)
        self.initialize_engine()
        plan = {"translation": "", "needs": []}
        if name == "graph_search":
            return None, self.engine.read_native(self.engine.rank(args["query"], plan))
        packet, _ = self.engine.query(args["query"], plan)
        return None, packet

    def initialize_engine(self):
        if self.engine is not None or self.arm == "grep":
            return
        if self.arm == "grep_bm25":
            from chapter2_baseline_native import NoGraphBM25
            self.engine = NoGraphBM25(self.protocol["corpus"], self.protocol["inputs"]["corpus_manifest"]["path"])
        elif self.arm == "grep_e5":
            from chapter2_baseline_native import DenseE5
            self.engine = DenseE5(self.protocol["corpus"], self.protocol["inputs"]["corpus_manifest"]["path"], self.protocol["e5_index"])
        else:
            from chapter2_graph_retriever import GraphRetriever
            self.engine = GraphRetriever(self.protocol["inputs"]["self_graph"]["path"], self.protocol["corpus"],
                                         corpus_manifest=self.protocol["inputs"]["corpus_manifest"]["path"])

    def execute(self, name, args, response_byte_cap=None):
        if len(self.events) >= LIMITS["tool_calls"]:
            raise ValueError("tool-call budget exhausted")
        started = time.monotonic()
        text, packet = self.invoke(name, args)
        added = []
        if packet is not None:
            native = canonicalize(packet, time.monotonic() - started)
            # 跨调用逐行去重；只把完整实际送达行加入seen，截断行以后仍可读取。
            candidates = []
            for unit in native:
                if unit.get("mapping_status") == "unmappable":
                    candidates.append(unit)
                    continue
                run = []
                def emit():
                    if run:
                        candidates.append({**unit, "start": run[0][0], "end": run[-1][0], "lines": [v for _, v in run]})
                        run.clear()
                for i, line in enumerate(unit["lines"], unit["start"]):
                    if (unit["path"], unit["source_sha256"], i) in self.seen:
                        emit()
                    else:
                        run.append((i, line))
                emit()
            for i, unit in enumerate(candidates, len(self.units) + 1):
                unit["first_rank"] = i
            remaining = LIMITS["new_evidence_characters"] - self.new_characters
            if remaining <= 0:
                text = "原文证据字符预算已耗尽。"
            else:
                budget = min(LIMITS["tool_characters"], remaining)
                delivery = render(candidates, budget)
                while response_byte_cap is not None and len(wire(delivery["text"]).encode()) - 2 > response_byte_cap:
                    budget = max(1, min(budget - 1, int(budget * response_byte_cap / (len(wire(delivery["text"]).encode()) - 2))))
                    delivery = render(candidates, budget)
                text = delivery["text"] or "未返回新的完整原文行；可更换查询或缩小读取范围。"
                for unit in delivery["units"]:
                    unit["cumulative_returned_characters"] += self.new_characters
                    unit["query_step"] = len(self.events) + 1
                    if unit.get("mapping_status") != "unmappable":
                        for i in range(unit["start"], unit["end"] + 1):
                            self.seen.add((unit["path"], unit["source_sha256"], i))
                    added.append(unit)
                self.new_characters += delivery["returned_characters"]
                self.units.extend(added)
        if response_byte_cap is not None and len(wire(text).encode()) - 2 > response_byte_cap:
            if name == "locate_files":
                value = json.loads(text)
                while value["paths"] and len(wire(wire(value)).encode()) - 2 > response_byte_cap:
                    value["paths"].pop()
                    value["truncated"] = True
                text = wire(value)
            else:
                text = "无空间返回完整原文行。"
            if len(wire(text).encode()) - 2 > response_byte_cap:
                text = ""
        event = {"name": name, "arguments": args, "seconds": time.monotonic() - started,
                 "response_characters": len(text), "new_evidence_units": added}
        self.events.append(event)
        return text


def input_bound(request):
    """UTF-8字节及消息模板余量作保守准入估计；实测指标只用provider usage。"""
    return len(wire(request).encode()) + 1024 * (len(request["messages"]) + 1)


class Provider:
    """代理调用与可恢复请求记录；只执行资源约束，不设置费用门槛。"""
    def __init__(self, root, settings):
        from chapter2_qwen_proxy_config import settings as proxy_settings
        self.root = Path(root)
        base, self.key = proxy_settings(Path(settings))
        self.endpoint = base + "/chat/completions"
        if (self.root / "protocol.json").exists():
            expected = load(self.root / "protocol.json")["provider"]
            if expected != {"name": "qwen_proxy", "endpoint": self.endpoint}:
                raise ValueError("proxy endpoint differs from frozen protocol")

    def __call__(self, request, folder, label):
        folder = Path(folder)
        response_file = folder / (label + ".json")
        request_hash = hashlib.sha256(wire(request).encode()).hexdigest()
        if response_file.exists():
            response = load(response_file)
            if response["request_sha256"] != request_hash:
                raise ValueError("resumed request drift")
            archived = response["seconds"] + sum(load(p)["seconds"] for p in folder.glob(label + ".error-*.json"))
            return {**response["response"], "_replayed_seconds": archived}
        input_tokens = input_bound(request)
        if input_tokens > LIMITS["request_input_tokens"]:
            raise ValueError("request admission bound exceeds input limit")
        for attempt in range(3):
            attempt_file = folder / f"{label}.attempt-{attempt}.json"
            if attempt_file.exists():
                continue  # 中断尝试仍占重试次数，不能无限恢复。
            save(attempt_file, {"request": request, "request_sha256": request_hash,
                               "provider": "qwen_proxy", "endpoint": self.endpoint})
            started = time.monotonic()
            req = urllib.request.Request(self.endpoint, wire(request).encode(),
                  {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
            try:
                with urllib.request.urlopen(req, timeout=180) as response:
                    raw = json.load(response)
            except (urllib.error.URLError, TimeoutError) as error:
                signals = []
                if isinstance(error, urllib.error.HTTPError):
                    try:
                        body = error.read(16384).decode(errors="replace").lower()
                        for signal in ("parallel_tool_calls", "response_format", "tool_choice", "tools", "model", "quota", "api key"):
                            if signal in body:
                                signals.append(signal)
                    except Exception:
                        pass
                save(folder / f"{label}.error-{attempt}.json", {"error_type": type(error).__name__,
                     "http_status": getattr(error, "code", None), "seconds": time.monotonic() - started,
                     "usage_unknown": True, "diagnostic_signals": signals})
                if isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                    raise RuntimeError("non-retryable provider error; inspect sanitized attempt record") from None
                continue
            save(response_file, {"request_sha256": request_hash, "response": raw,
                 "provider": "qwen_proxy", "endpoint": self.endpoint, "seconds": time.monotonic() - started})
            actual_in, actual_out = usage(raw)
            if actual_in > LIMITS["request_input_tokens"] or actual_out > request["max_tokens"]:
                raise ValueError("provider usage exceeded frozen request limits")
            return raw
        raise TransportFailure("transport attempts exhausted; no model/provider fallback")


class TransportFailure(RuntimeError):
    pass


def environment():
    from importlib.metadata import PackageNotFoundError, version
    packages = {}
    for name in ("numpy", "torch", "sentence-transformers", "transformers"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"python": sys.version, "packages": packages}


def usage(response):
    value = response.get("usage", {})
    counts = [value.get("prompt_tokens"), value.get("completion_tokens")]
    if any(type(v) is not int or v < 0 for v in counts):
        raise ValueError("provider token usage missing; no invented token totals")
    if response.get("model") and response["model"] != "qwen3-8b":
        raise ValueError("unexpected response model identity")
    return counts


def request(messages, arm, final=False, output_tokens=2400):
    result = {"model": "qwen3-8b", "temperature": 0, "enable_thinking": False,
              "max_tokens": output_tokens, "response_format": {"type": "json_object"}, "messages": messages}
    if not final:
        encoded = [dict(m) for m in messages]
        encoded[0]["content"] += "\n可用工具说明：" + wire([t["function"] for t in tools_for(arm)])
        result["messages"] = encoded
    return result


def run_session(protocol, arm, question, fetch, folder, engine=None):
    session = ToolSession(protocol, arm, engine)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question["question"]}]
    trace, total_input, total_output, status, answer, error = [], 0, 0, "failed", None, None
    admitted_input = 0
    started = time.monotonic()
    for turn in range(9):
        normal_bound = input_bound(request(messages, arm))
        consumed = max(total_input, admitted_input)
        force_final = (len(session.events) >= LIMITS["tool_calls"] or
                       normal_bound > LIMITS["request_input_tokens"] - LIMITS["final_context_headroom"] or
                       consumed + normal_bound > LIMITS["session_input_tokens"] - LIMITS["request_input_tokens"])
        candidate_messages = messages + [{"role": "user", "content": "资源限制已到，请仅输出action=final的最终回答JSON。"}] if force_final else messages
        candidate = request(candidate_messages, arm, final=force_final)
        bound = input_bound(candidate)
        if bound > LIMITS["request_input_tokens"] or max(total_input, admitted_input) + bound > LIMITS["session_input_tokens"]:
            error = "input_budget_exhausted_without_valid_final_answer"
            break
        try:
            response = fetch(candidate, folder, f"turn-{turn:02d}")
        except TransportFailure:
            error = "transport_attempts_exhausted; failed_attempt_tokens_unknown"
            break
        inp, out = usage(response)
        admitted_input += bound
        total_input += inp
        total_output += out
        trace.append({"turn": turn, "input_tokens": inp, "output_tokens": out, "usage": response["usage"],
                      "forced_final": force_final, "response": response})
        if inp > LIMITS["request_input_tokens"] or out > LIMITS["answer_output_tokens"] or total_input > LIMITS["session_input_tokens"]:
            raise ValueError("provider exceeded frozen token limit")
        choice = response["choices"][0]
        message = choice["message"]
        if message.get("tool_calls"):
            error = "unexpected_native_tool_call_in_json_action_protocol"
            break
        try:
            if choice.get("finish_reason") != "stop":
                raise ValueError("truncated action response")
            action = json.loads(message.get("content") or "")
            if not isinstance(action, dict) or action.get("action") not in {"tool", "final"}:
                raise ValueError("invalid JSON action")
        except (ValueError, TypeError) as exc:
            error = str(exc)
            break
        if action["action"] == "tool":
            if force_final or set(action) != {"action", "name", "arguments"} or not isinstance(action["name"], str):
                error = "invalid_tool_action_or_tool_budget_exhausted"
                break
            name, arguments = action["name"], action["arguments"]
            assistant_message = {"role": "assistant", "content": message["content"]}
            tool_message = {"role": "user", "content": "工具返回 " + name + ":\n"}
            final_bound = input_bound(request(messages + [assistant_message, tool_message,
                          {"role": "user", "content": "资源限制已到，请仅输出action=final的最终回答JSON。"}], arm, final=True))
            response_space = min(LIMITS["request_input_tokens"], LIMITS["session_input_tokens"] - max(total_input, admitted_input)) - final_bound
            if response_space <= 0:
                error = "insufficient_context_for_tool_response_and_final_answer"
                break
            try:
                content = session.execute(name, arguments, response_byte_cap=response_space)
            except ValueError as exc:
                content = "工具参数错误：" + str(exc)
                session.events.append({"name": name, "arguments": arguments,
                                       "error": str(exc), "new_evidence_units": [], "seconds": 0})
            tool_message["content"] += content
            messages.extend([assistant_message, tool_message])
        else:
            try:
                if set(action) != {"action", "answer"}:
                    raise ValueError("invalid final action schema")
                answer = action["answer"]
                validate(answer, {"units": session.units})
                status = "complete_structure"
            except (ValueError, TypeError, KeyError) as exc:
                error = str(exc)
            break
    return {"schema": "retrieval-augmentation-session-v1", "arm": arm, "question": question,
            "status": status, "answer": answer, "error": error, "input_tokens": total_input,
            "output_tokens": total_output, "tool_calls": len(session.events), "tools": session.events,
            "admitted_input_upper": admitted_input,
            "delivery": session.units, "trace": trace,
            "wall_seconds": time.monotonic() - started + sum(t["response"].get("_replayed_seconds", 0.) for t in trace),
            "new_evidence_characters": session.new_characters,
            "limits": "coordinate-valid answer is not a correctness score; same8B generator/judge"}


def dependency_sources(directory):
    """只快照新入口的本地静态/常量动态导入闭包，不复制无关历史工作脚本。"""
    directory = Path(directory)
    pending = {"chapter2_augmentation", "chapter2_augmentation_evaluation", "chapter2_augmentation_cleanup", "chapter2_augmentation_campaign"}
    found = set()
    while pending:
        name = pending.pop()
        source = directory / (name + ".py")
        if name in found or not source.is_file():
            continue
        found.add(name)
        for node in ast.walk(ast.parse(source.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "import_module" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                names = [node.args[0].value.split(".")[0]]
            pending.update(n for n in names if n not in found and (directory / (n + ".py")).is_file())
    return [directory / (name + ".py") for name in sorted(found)]


def prepare(root, legacy, research, settings_file):
    root, legacy, research = Path(root).resolve(), Path(legacy).resolve(), Path(research).resolve()
    if root.exists():
        raise FileExistsError("new archive destination required")
    old = load(legacy / "formal/frozen_001/protocol.json")
    if sha(legacy / "formal/frozen_001/protocol.json") != load(legacy / "formal/frozen_001/seal.json")["protocol_sha256"]:
        raise ValueError("legacy protocol drift")
    for name in ("questions", "corpus_manifest", "self_graph"):
        item = old["public_inputs"][name]
        if sha(item["path"]) != item["sha256"]:
            raise ValueError("legacy input drift: " + name)
    dataset = legacy / "datasets/frozen_001"
    root.mkdir(parents=True)
    for relative, source in (("public/test.questions.json", dataset / "public_test/questions.json"),
                             ("public/dev.questions.json", dataset / "development/dev.questions.json"),
                             ("public/corpus-manifest.json", dataset / "corpus-manifest.json"),
                             ("evaluation_only/test.annotations.json", dataset / "evaluation_only/test.annotations.json"),
                             ("evaluation_only/dev.annotations.json", dataset / "development/dev.annotations.json")):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for source in dependency_sources(Path(__file__).parent):
        target = root / "runtime" / source.name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
    from chapter2_qwen_proxy_config import settings as proxy_settings
    base, _ = proxy_settings(settings_file)
    private = root / "local_private"
    private.mkdir(mode=0o700)
    secret_copy = private / ".env.qwen_proxy"
    with secret_copy.open("xb") as stream:
        stream.write(Path(settings_file).read_bytes())
    secret_copy.chmod(0o600)
    for name in ("README.md", "OVERVIEW.md", "chapters/chapter02.md"):
        target = root / "design_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(research / name, target)
    questions = load(root / "public/test.questions.json")
    annotations = load(root / "evaluation_only/test.annotations.json")
    rng = random.Random(20261011)
    selected = []
    for category, count in (("cross", 5), ("manual", 2), ("tutorial", 1)):
        families = sorted(a["id"] for a in annotations if a["category"] == category)
        rng.shuffle(families)
        if len(families) < count:
            raise ValueError("insufficient review stratum")
        selected.extend(families[:count])
    save(root / "evaluation_only/review-sample.json", {"seed": 20261011, "families": selected,
         "selection": "stratified before outcomes; all variants/repeats/arms", "sessions": 288,
         "limits": "same-model repeated grading, not independent validation"})
    inputs = {"test_questions": {"path": str(root / "public/test.questions.json")},
              "dev_questions": {"path": str(root / "public/dev.questions.json")},
              "corpus_manifest": {"path": str(root / "public/corpus-manifest.json")},
              "self_graph": old["public_inputs"]["self_graph"]}
    for item in inputs.values():
        item["sha256"] = sha(item["path"])
    protocol = {"schema": "grep-retrieval-augmentation-v4", "date": "2026-10-11", "model": "qwen3-8b",
                "arms": ARMS, "repeats": 3, "seed": 20261011, "limits": LIMITS,
                "provider": {"name": "qwen_proxy", "endpoint": base + "/chat/completions"},
                "agent_tool_protocol": "explicit-json-action-v1; tool schemas included in system text; no native tool fields",
                "system_prompt": SYSTEM, "tool_schemas": {a: tools_for(a) for a in ARMS},
                "inputs": inputs, "corpus": old["paths"]["corpus"], "e5_index": old["paths"]["e5_index"],
                "e5_manifest_sha256": sha(Path(old["paths"]["e5_index"]) / "manifest.json"),
                "source_protocol_sha256": sha(legacy / "formal/frozen_001/protocol.json"),
                "planned_sessions": len(questions) * 4 * 3, "independent_test_families": 32,
                "mechanism": {"arms": ABLATIONS, "budgets": [6000, 12000, 24000], "primary_budget": 24000,
                              "primary_comparison": "full-no_cross on cross-source families"},
                "statistics": {"unit": "family", "resamples": 10000, "ci": .95, "multiplicity": "Holm three paired comparisons"},
                "environment": environment(),
                "paid_run_authorization": "user explicitly authorized paid experiment without a monetary cap on 2026-10-11",
                "isolation": "production audit guard denies gold/data-design/subprocess; not an OS sandbox",
                "historical_limits": "known questions and corpus; no unseen-question/knowledge claim; same8B judge provisional"}
    save(root / "protocol.json", protocol)
    protected = list((root / "public").glob("*.json")) + list((root / "evaluation_only").glob("*.json"))
    protected += list((root / "runtime").glob("*.py")) + list((root / "design_snapshot").rglob("*.md"))
    save(root / "seal.json", {"protocol_sha256": sha(root / "protocol.json"),
         "files": {str(p.relative_to(root)): sha(p) for p in sorted(protected)}})
    (root / "README.md").write_text("# 第2章基础agent检索增强实验\n\n"
         "更新时间：2026-10-11。已准备新协议、运行快照和评分侧材料；用户已授权直接启动付费运行，新收益结果尚未生成。\n\n"
         "四组均保留grep、文件定位、原文读取，另三组分别增加BM25、E5、图谱；问答/裁判均qwen3-8b，用户指定qwen_proxy。\n\n"
         "详细工程协议与命令见[维护计划](../../../PrincipiaBlastFoam-DSH/experiments/retrieval_method/AUGMENTATION_PLAN.md)。"
         "冻结入口为protocol.json和seal.json，design_snapshot保存采用设计版本。"
         "evaluation_only仅供评分，local_private为Git忽略的私有代理配置，不进入seal。\n\n"
         "旧aliyun_8b_cross_source_v1保留历史身份。人工评分不作为本协议要求。同模型重评只验证稳定性，不是独立真值。\n", encoding="utf-8")
    return protocol


def verify(root, production=False):
    root = Path(root).resolve()
    seal, protocol = load(root / "seal.json"), load(root / "protocol.json")
    if sha(root / "protocol.json") != seal["protocol_sha256"]:
        raise ValueError("protocol drift")
    for relative, expected in seal["files"].items():
        if production and relative.startswith("evaluation_only/"):
            continue  # 正式被测进程不读取评分侧材料，离线check负责完整seal核验。
        if sha(root / relative) != expected:
            raise ValueError("sealed input/runtime drift: " + relative)
    for item in protocol["inputs"].values():
        if sha(item["path"]) != item["sha256"]:
            raise ValueError("public input drift")
    if sha(Path(protocol["e5_index"]) / "manifest.json") != protocol["e5_manifest_sha256"]:
        raise ValueError("E5 index manifest drift")
    for path, expected in load(protocol["inputs"]["corpus_manifest"]["path"])["files"].items():
        if sha(Path(protocol["corpus"]) / path) != expected:
            raise ValueError("authoritative corpus drift")
    if protocol["limits"] != LIMITS or protocol["system_prompt"] != SYSTEM or protocol["tool_schemas"] != {a: tools_for(a) for a in ARMS}:
        raise ValueError("runtime interface differs from frozen protocol")
    if protocol["environment"] != environment():
        raise ValueError("frozen interpreter/package versions differ")
    return protocol


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "check", "launch", "run", "mechanism"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--legacy", type=Path)
    p.add_argument("--research", type=Path)
    p.add_argument("--split", choices=("dev", "test"), default="dev")
    p.add_argument("--arm", choices=ARMS)
    p.add_argument("--question-id", help="development contract check; reuses the same frozen session in full grid")
    p.add_argument("--repeat", type=int, choices=(1, 2, 3))
    p.add_argument("--settings-file", type=Path)
    args = p.parse_args()
    root = args.root.resolve()
    if args.command == "prepare":
        if not args.legacy or not args.research or not args.settings_file:
            p.error("prepare requires --legacy, --research and --settings-file for private proxy copy")
        prepare(root, args.legacy, args.research, args.settings_file)
        print(wire({"prepared": str(root), "paid_calls": 0}))
        return
    if args.command == "check":
        protocol = verify(root)
        print(wire({"status": "verified", "sessions": protocol["planned_sessions"], "paid_calls": 0}))
        return
    if Path(__file__).resolve() != root / "runtime" / Path(__file__).name:
        raise ValueError("execute archived runtime snapshot")
    if args.command == "launch":
        if not args.settings_file:
            p.error("launch requires proxy settings")
        verify(root)
        Provider(root, args.settings_file)  # 验证代理身份，仍不请求网络。
        import subprocess
        from concurrent.futures import ThreadPoolExecutor
        order = list(ARMS)
        random.Random(20261011).shuffle(order)
        def launch(arm):
            return subprocess.run([sys.executable, str(Path(__file__).resolve()), "run", "--root", str(root),
                 "--split", args.split, "--arm", arm, "--settings-file", str(args.settings_file.resolve())], check=False).returncode
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = dict(zip(order, pool.map(launch, order)))
        if any(results.values()):
            raise RuntimeError("one or more arms incomplete; preserve planned grid and inspect logs")
        return
    from chapter2_production_guard import install
    install(allow_test_public=True)
    protocol = verify(root, production=True)
    if not args.settings_file:
        p.error("paid run requires proxy settings")
    if args.command == "run" and not args.arm:
        p.error("run requires --arm; each arm runs in an isolated process")
    provider = Provider(root, args.settings_file)
    questions = load(protocol["inputs"][args.split + "_questions"]["path"])
    if args.question_id or args.repeat:
        if args.split != "dev" or args.command != "run":
            p.error("question/repeat selection is development-only")
        if args.question_id:
            questions = [q for q in questions if q["id"] == args.question_id]
            if len(questions) != 1:
                p.error("unknown development question")
    repeats = (args.repeat,) if args.repeat else range(1, 4)
    jobs = [(r, q, a) for r in repeats for q in questions for a in ((args.arm,) if args.command == "run" else ("mechanism",))]
    random.Random(protocol["seed"]).shuffle(jobs)
    if args.command == "mechanism":
        from chapter2_augmentation_evaluation import run_mechanism
        run_mechanism(root, protocol, questions, provider, args.split)
        return
    setup = ToolSession(protocol, args.arm)
    setup_started = time.monotonic()
    setup.initialize_engine()
    save(root / "setup" / (f"{args.arm}-{time.time_ns()}.json"), {"arm": args.arm,
         "load_seconds": time.monotonic() - setup_started, "protocol_sha256": sha(root / "protocol.json"),
         "limits": "process setup separate from per-task agent wall time; no cross-query evidence/embedding cache"})
    for repeat, question, arm in jobs:
        folder = root / "runs" / args.split / question["id"] / f"r{repeat}" / arm
        compiled = folder / "session.json"
        if compiled.exists():
            if load(compiled)["protocol_sha256"] != sha(root / "protocol.json"):
                raise ValueError("resumed session protocol drift")
            continue
        record = run_session(protocol, arm, question, provider, folder, setup.engine)
        save(compiled, {**record, "repeat": repeat, "protocol_sha256": sha(root / "protocol.json"),
                       "response_sha256": {p.name: sha(p) for p in folder.glob("turn-*.json")}})
        print(question["id"], repeat, arm, record["status"], flush=True)


if __name__ == "__main__":
    main()
