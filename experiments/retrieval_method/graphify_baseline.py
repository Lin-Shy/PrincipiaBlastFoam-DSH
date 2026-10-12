"""官方 Graphify 的隔离语料冻结、原生构建和逐 HTTP 尝试计量。

不改 Graphify 的提示词、分块、合并或查询算法；不读取评测题/标准答案。
由隔离安装了 graphifyy 的 Python 运行。所有生成物进入外部归档目录。
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import threading
import time
import traceback


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value, secret=""):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if secret:
        text = text.replace(secret, "[REDACTED]")
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        os.chmod(temp, 0o600)
        handle.write(text)
    temp.replace(path)


def git(upstream, *args):
    return subprocess.check_output(
        ["git", "-C", str(upstream), *args], text=True
    ).strip()


def package_identity(upstream):
    import graphify
    installed = Path(graphify.__file__).parent
    source = upstream / "graphify"
    changed = git(upstream, "diff", "HEAD", "--", "graphify", "pyproject.toml")
    if changed:
        raise ValueError("Upstream implementation has tracked modifications")
    hashes = {}
    for path in sorted(source.rglob("*.py")):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts:
            continue
        expected = path.read_bytes()
        actual = (installed / relative).read_bytes()
        if expected != actual:
            raise ValueError(f"Installed Graphify differs from upstream: {relative}")
        hashes[str(relative)] = sha(actual)
    return {
        "repository": "https://github.com/Graphify-Labs/graphify",
        "commit": git(upstream, "rev-parse", "HEAD"),
        "package": "graphifyy",
        "version": importlib.metadata.version("graphifyy"),
        "python": sys.version,
        "implementation_files_sha256": hashes,
        "implementation_identity": sha(json.dumps(hashes, sort_keys=True).encode()),
        "installed_matches_upstream": True,
        "dependency_freeze": subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze", "--all"], text=True
        ).splitlines(),
    }


def prepare(args):
    """只复制用户指定的两个子树；不把索引、人工补充或评测文件带入语料。"""
    from graphify.detect import detect
    archive = args.archive.resolve()
    destination = archive / "corpus_native"
    if destination.exists() or (archive / "corpus_manifest.json").exists():
        raise FileExistsError("Frozen corpus already exists; use another archive")
    identity = package_identity(args.upstream.resolve())
    rows = []
    for prefix in (Path("manual/markdown"), Path("tutorials")):
        source = args.source_corpus.resolve() / prefix
        if not source.is_dir():
            raise ValueError(f"Missing source subtree: {prefix}")
        for original in sorted(source.rglob("*")):
            if original.is_symlink():
                raise ValueError(f"Symlink requires explicit scope review: {original}")
            if not original.is_file():
                continue
            relative = prefix / original.relative_to(source)
            data = original.read_bytes()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            if target.read_bytes() != data:
                raise ValueError("Corpus copy mismatch")
            try:
                data.decode("utf-8")
                utf8_text = b"\0" not in data
            except UnicodeError:
                utf8_text = False
            rows.append({
                "path": relative.as_posix(), "original_path": str(original),
                "source": "manual" if prefix.parts[0] == "manual" else "tutorials",
                "sha256": sha(data), "bytes": len(data),
                "suffix": original.suffix, "utf8_text": utf8_text,
            })
    corpus_id = sha(json.dumps(
        [{k: row[k] for k in ("path", "sha256", "bytes")} for row in rows],
        sort_keys=True, ensure_ascii=False,
    ).encode())
    write_json(archive / "corpus_manifest.json", {
        "schema": "graphify-baseline-corpus-v1", "created_at": now(),
        "corpus_id": corpus_id, "files": rows,
        "file_count": len(rows), "bytes": sum(row["bytes"] for row in rows),
        "scope": ["manual/markdown", "tutorials"],
        "contains_evaluation_questions_or_gold": False,
    })
    write_json(archive / "upstream_identity.json", identity)
    detection = detect(destination, cache_root=archive / "preflight_native")
    write_json(archive / "native_detection.json", detection)
    counts = {k: len(v) for k, v in detection["files"].items()}
    write_json(archive / "native_coverage.json", {
        "corpus_id": corpus_id, "input_files": len(rows),
        "detected_by_type": counts,
        "unclassified": len(detection["unclassified"]),
        "skipped_sensitive": detection["skipped_sensitive"],
        "walk_errors": detection["walk_errors"],
        "ignored": detection["ignored"],
        "note": "Recognition is not successful extraction or factual accuracy.",
    })
    print(json.dumps({"corpus_id": corpus_id, "input_files": len(rows),
                      "detected": counts, "unclassified": len(detection["unclassified"])}))


def verify_corpus(archive, variant):
    manifest = json.loads((archive / "corpus_manifest.json").read_text())
    root = archive / ("corpus_native" if variant == "native" else "corpus_text_adapter")
    mapping = {row["path"]: row["path"] for row in manifest["files"]}
    if variant != "native":
        mapping = json.loads((archive / "text_adapter_manifest.json").read_text())["path_map"]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(mapping.values()):
        raise ValueError("Frozen corpus file set changed")
    for row in manifest["files"]:
        if sha((root / mapping[row["path"]]).read_bytes()) != row["sha256"]:
            raise ValueError(f"Frozen corpus content changed: {row['path']}")
    return root, manifest, mapping


def adapt(args):
    """独立格式适配变体：只把原生未分类的 UTF-8 文本副本追加 .txt。"""
    from graphify.detect import detect
    archive = args.archive.resolve()
    source, manifest, _ = verify_corpus(archive, "native")
    destination = archive / "corpus_text_adapter"
    if destination.exists():
        raise FileExistsError("Text adapter corpus already exists")
    detection = json.loads((archive / "native_detection.json").read_text())
    unclassified = {Path(p).relative_to(source).as_posix() for p in detection["unclassified"]}
    mapping, renamed = {}, []
    for row in manifest["files"]:
        original = row["path"]
        target = original + ".txt" if original in unclassified and row["utf8_text"] else original
        if target in mapping.values():
            raise ValueError("Adapter path collision")
        mapping[original] = target
        if target != original:
            renamed.append(original)
        (destination / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / original, destination / target)
    write_json(archive / "text_adapter_manifest.json", {
        "variant": "graphify+lossless-text-extension-adapter",
        "corpus_id": manifest["corpus_id"], "created_at": now(),
        "transformation": "Append .txt to originally unclassified UTF-8 non-NUL files; bytes unchanged",
        "renamed_files": renamed, "path_map": mapping,
        "domain_parser_or_manual_annotations": False,
    })
    verify_corpus(archive, "text_adapter")
    adapted = detect(destination, cache_root=archive / "preflight_text_adapter")
    write_json(archive / "text_adapter_detection.json", adapted)
    print(json.dumps({"renamed": len(renamed), "detected": {
        k: len(v) for k, v in adapted["files"].items()},
        "unclassified": len(adapted["unclassified"])}))


class Audit:
    """在 SDK 的 HTTP 发送边界留痕，包含 SDK 重试与被 Graphify 丢弃的响应。"""
    def __init__(self, directory, secret, expected_model="deepseek-flash"):
        self.directory = directory
        self.secret = secret
        self.expected_model = expected_model
        self.lock = threading.Lock()
        self.sequence = 0
        self.http = []
        self.reads = collections.Counter()

    def install_http(self):
        from openai import _base_client
        # SDK 3.x may import httpx2 as httpx. Hook its actual transport module.
        module = getattr(_base_client, "httpx", None) or _base_client.httpx2
        original = module.Client.send
        audit = self

        def send(client, request, *args, **kwargs):
            if request.url.host != "api.deepseek.com":
                raise RuntimeError("Unexpected model endpoint; baseline uses explicit DeepSeek routing")
            with audit.lock:
                audit.sequence += 1
                sequence = audit.sequence
            started = time.perf_counter()
            body = request.content
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                payload = {"unparsed_body_sha256": sha(body), "bytes": len(body)}
            item = {
                "sequence": sequence, "started_at": now(), "state": "in_flight",
                "method": request.method, "host": request.url.host,
                "path": request.url.path, "request_sha256": sha(body),
                "request_bytes": len(body), "request": payload,
                "usage": None,
            }
            path = audit.directory / "http" / f"{sequence:05d}.json"
            write_json(path, item, audit.secret)
            try:
                response = original(client, request, *args, **kwargs)
                raw = response.read()
                item.update(state="response", status_code=response.status_code,
                            response_bytes=len(raw), response_sha256=sha(raw))
                try:
                    parsed = json.loads(raw)
                    item["response"] = parsed
                    if isinstance(parsed, dict):
                        item["usage"] = parsed.get("usage")
                        item["provider_model"] = parsed.get("model")
                        if parsed.get("choices") and parsed.get("model") != audit.expected_model:
                            item["state"] = "model_mismatch"
                            raise RuntimeError(
                                f"Provider returned {parsed.get('model')!r}; "
                                f"expected {audit.expected_model!r}"
                            )
                except (ValueError, UnicodeError):
                    item["response_text"] = raw.decode("utf-8", errors="replace")
                return response
            except BaseException as error:
                if item.get("state") != "model_mismatch":
                    item["state"] = "transport_error"
                item["error_type"] = type(error).__name__
                raise
            finally:
                item.update(finished_at=now(), elapsed_seconds=time.perf_counter() - started)
                write_json(path, item, audit.secret)
                with audit.lock:
                    audit.http.append({k: v for k, v in item.items()
                                       if k not in {"request", "response", "response_text"}})
        module.Client.send = send
        return lambda: setattr(module.Client, "send", original)

    def install_reads(self):
        originals = {name: getattr(Path, name) for name in ("read_text", "read_bytes")}
        audit = self
        for name, original in originals.items():
            def reader(path, *args, _original=original, _name=name, **kwargs):
                value = _original(path, *args, **kwargs)
                with audit.lock:
                    audit.reads[(_name, str(path), "calls")] += 1
                    audit.reads[(_name, str(path), "bytes" if isinstance(value, bytes) else "chars")] += len(value)
                return value
            setattr(Path, name, reader)
        def restore():
            for name, original in originals.items():
                setattr(Path, name, original)
        return restore

    def summary(self):
        usage = collections.Counter()
        for item in self.http:
            for key, value in (item.get("usage") or {}).items():
                if isinstance(value, (int, float)):
                    usage[key] += value
        return {
            "http_attempts": len(self.http),
            "response_count": sum(x["state"] == "response" for x in self.http),
            "transport_errors": sum(x["state"] == "transport_error" for x in self.http),
            "model_mismatches": sum(x["state"] == "model_mismatch" for x in self.http),
            "provider_models": sorted({x.get("provider_model") for x in self.http if x.get("provider_model")}),
            "unknown_usage_attempts": sum(not x.get("usage") for x in self.http),
            "reported_usage_sum": dict(usage),
            "reported_usage_is_lower_bound": any(not x.get("usage") for x in self.http),
            "request_bytes_all_attempts": sum(x["request_bytes"] for x in self.http),
            "http_elapsed_seconds_sum": sum(x["elapsed_seconds"] for x in self.http),
            "path_read_counters": [{"operation": op, "path": path, "unit": unit, "value": value}
                                   for (op, path, unit), value in sorted(self.reads.items())],
            "read_meter_limit": "Path.read_text/read_bytes only; builtins.open/native reads not covered. Not full I/O accounting.",
            "cost_scope": "Construction only; every SDK HTTP attempt retained, including retries and responses rejected by Graphify. No dollar estimate.",
        }


class SafeTee(io.TextIOBase):
    def __init__(self, stream, log, secret):
        self.stream, self.log, self.secret = stream, log, secret
        self.lock = threading.Lock()

    def write(self, value):
        safe = value.replace(self.secret, "[REDACTED]") if self.secret else value
        with self.lock:
            self.log.write(safe)
            self.log.flush()
            self.stream.write(safe)
            self.stream.flush()
        return len(value)

    def flush(self):
        self.log.flush()
        self.stream.flush()


def build(args):
    if args.model != "deepseek-flash":
        raise ValueError("Chapter 2 graph construction is locked to deepseek-flash")
    archive = args.archive.resolve()
    corpus, manifest, _ = verify_corpus(archive, args.variant)
    expected = json.loads((archive / "upstream_identity.json").read_text())
    identity = package_identity(args.upstream.resolve())
    if identity["implementation_identity"] != expected["implementation_identity"]:
        raise ValueError("Graphify implementation identity changed")
    run_root = archive / args.variant
    attempts = run_root / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    number = max([int(p.name) for p in attempts.iterdir() if p.is_dir()] or [0]) + 1
    attempt = attempts / f"{number:03d}"
    attempt.mkdir()
    # Read the credential only in this process. Never serialize headers or env.
    secret = args.key_file.read_text().strip()
    if not secret or any(c.isspace() for c in secret):
        raise ValueError("Credential file must contain one API key")
    cleared = sorted(k for k in os.environ if k.startswith("GRAPHIFY_"))
    for key in cleared:
        os.environ.pop(key, None)
    os.environ["DEEPSEEK_API_KEY"] = secret
    os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
    # Do not inherit verbose SDK logging, which could expose request headers.
    os.environ.pop("OPENAI_LOG", None)
    argv = ["graphify", "extract", str(corpus), "--backend", "deepseek",
            "--model", args.model, "--out", str(run_root), "--max-workers", "1",
            "--max-concurrency", str(args.max_concurrency), "--token-budget", str(args.token_budget),
            "--api-timeout", str(args.api_timeout), "--timing"]
    config = {
        "created_at": now(), "state": "running", "argv": argv,
        "variant": args.variant, "corpus_id": manifest["corpus_id"],
        "upstream_commit": identity["commit"], "package_version": identity["version"],
        "implementation_identity": identity["implementation_identity"],
        "driver_sha256": sha(Path(__file__).read_bytes()),
        "inherited_graphify_env_names_cleared": cleared,
        "credential": "provided in process environment; value and headers not archived",
        "thinking": "native provider default; not overridden",
        "dedup": "native default", "clustering": "native default",
        "sdk_retries": "Graphify default (6)", "resume": number > 1,
    }
    write_json(attempt / "run.json", config, secret)
    shutil.copy2(__file__, attempt / "frozen_driver.py")
    audit = Audit(attempt, secret, expected_model=args.model)
    restore_http = audit.install_http()
    restore_reads = audit.install_reads()
    start = time.perf_counter()
    usage_start = resource.getrusage(resource.RUSAGE_SELF)
    code = 0
    try:
        with (attempt / "console.log").open("w", encoding="utf-8") as log:
            os.chmod(attempt / "console.log", 0o600)
            with contextlib.redirect_stdout(SafeTee(sys.stdout, log, secret)), \
                    contextlib.redirect_stderr(SafeTee(sys.stderr, log, secret)):
                sys.argv = argv
                try:
                    from graphify.__main__ import main
                    main()
                except SystemExit as error:
                    code = error.code if isinstance(error.code, int) else 1
                except BaseException:
                    code = 1
                    traceback.print_exc()
    finally:
        elapsed = time.perf_counter() - start
        restore_http()
        restore_reads()
        usage_end = resource.getrusage(resource.RUSAGE_SELF)
        config.update(state="completed" if code == 0 else "failed", exit_code=code,
                      finished_at=now(), elapsed_seconds=elapsed)
        metrics = audit.summary()
        metrics.update(elapsed_seconds=elapsed,
                       cpu_user_seconds=usage_end.ru_utime - usage_start.ru_utime,
                       cpu_system_seconds=usage_end.ru_stime - usage_start.ru_stime,
                       max_rss_kib=usage_end.ru_maxrss)
        write_json(attempt / "run.json", config, secret)
        write_json(attempt / "costs.json", metrics, secret)
        verify_corpus(archive, args.variant)
        print(json.dumps({"state": config["state"], "attempt": str(attempt),
                          "http_attempts": metrics["http_attempts"],
                          "reported_usage_sum": metrics["reported_usage_sum"]}))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("prepare")
    freeze.add_argument("--source-corpus", type=Path, required=True)
    freeze.add_argument("--upstream", type=Path, required=True)
    freeze.add_argument("--archive", type=Path, required=True)
    adapter = sub.add_parser("adapt")
    adapter.add_argument("--archive", type=Path, required=True)
    runner = sub.add_parser("build")
    runner.add_argument("--archive", type=Path, required=True)
    runner.add_argument("--upstream", type=Path, required=True)
    runner.add_argument("--key-file", type=Path, required=True)
    runner.add_argument("--variant", choices=["native", "text_adapter"], default="native")
    runner.add_argument("--model", default="deepseek-flash")
    runner.add_argument("--max-concurrency", type=int, default=3)
    runner.add_argument("--token-budget", type=int, default=60000)
    runner.add_argument("--api-timeout", type=float, default=180)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "adapt":
        adapt(args)
    else:
        return build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
