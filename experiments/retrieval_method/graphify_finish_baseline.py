"""用官方 cluster-only 完成报告和可视化；保留抽取阶段原图与独立成本。"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

from graphify_baseline import Audit, SafeTee, now, sha, verify_corpus, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--variant", choices=["native", "text_adapter"], required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-flash")
    args = parser.parse_args()
    if args.model != "deepseek-flash":
        raise ValueError("Chapter 2 graph presentation is locked to deepseek-flash")
    archive = args.archive.resolve()
    verify_corpus(archive, args.variant)
    run = archive / args.variant
    graph = run / "graphify-out/graph.json"
    if not graph.is_file():
        raise FileNotFoundError("No extracted Graphify graph")
    attempts = sorted((run / "attempts").glob("*/run.json"))
    if not attempts or json.loads(attempts[-1].read_text())["state"] != "completed":
        raise ValueError("Extraction process has not finished successfully")
    stage = run / "presentation"
    if stage.exists():
        raise FileExistsError("Presentation stage already exists; preserve its outputs")
    stage.mkdir()
    # cluster-only legitimately rewrites graph.json. Preserve the extraction
    # snapshot first, then freeze the final identity only after both stages.
    snapshot = run / "extract-output"
    snapshot.mkdir(exist_ok=False)
    for name in ("graph.json", ".graphify_analysis.json", "manifest.json", ".graphify_root"):
        source = graph.parent / name
        if source.exists():
            shutil.copy2(source, snapshot / name)
    secret = args.key_file.read_text().strip()
    if not secret or any(c.isspace() for c in secret):
        raise ValueError("Credential file must contain one API key")
    for key in list(os.environ):
        if key.startswith("GRAPHIFY_"):
            os.environ.pop(key)
    os.environ.pop("OPENAI_LOG", None)
    os.environ["DEEPSEEK_API_KEY"] = secret
    os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
    os.environ["GRAPHIFY_API_TIMEOUT"] = "180"
    argv = ["graphify", "cluster-only", str(run), "--backend", "deepseek",
            "--model", args.model, "--max-concurrency", "3", "--timing"]
    config = {"created_at": now(), "state": "running", "argv": argv,
              "input_graph_sha256": sha(graph.read_bytes()),
              "driver_sha256": sha(Path(__file__).read_bytes()),
              "model": args.model, "credential_archived": False}
    write_json(stage / "run.json", config, secret)
    shutil.copy2(__file__, stage / "frozen_driver.py")
    audit = Audit(stage, secret, expected_model=args.model)
    restore_http = audit.install_http()
    restore_reads = audit.install_reads()
    start = time.perf_counter()
    code = 1
    try:
        with (stage / "console.log").open("w", encoding="utf-8") as log:
            os.chmod(stage / "console.log", 0o600)
            with contextlib.redirect_stdout(SafeTee(sys.stdout, log, secret)), \
                    contextlib.redirect_stderr(SafeTee(sys.stderr, log, secret)):
                try:
                    from graphify.__main__ import main as graphify_main
                    sys.argv = argv
                    graphify_main()
                    code = 0
                except SystemExit as error:
                    code = error.code if isinstance(error.code, int) else 1
                except BaseException:
                    traceback.print_exc()
    finally:
        restore_http()
        restore_reads()
        elapsed = time.perf_counter() - start
        config.update(state="completed" if code == 0 else "failed", exit_code=code,
                      elapsed_seconds=elapsed, finished_at=now())
        metrics = audit.summary()
        metrics["elapsed_seconds"] = elapsed
        write_json(stage / "run.json", config, secret)
        write_json(stage / "costs.json", metrics, secret)
        verify_corpus(archive, args.variant)
        print(json.dumps({"state": config["state"], "http_attempts": metrics["http_attempts"],
                          "reported_usage_sum": metrics["reported_usage_sum"]}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
