"""独立恢复原评分传输失败；沿用封存模型/提示词/校验，不覆盖原评分。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time


def status(revision, value):
    target = revision / "STATUS.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({**value, "pid": os.getpid(), "updated_unix": time.time()}, ensure_ascii=False, indent=2) + "\n")
    temp.replace(target)


def prepare(core, root, revision, exporter):
    if revision.exists():
        raise FileExistsError("new transport recovery archive required")
    core.verify(root)
    revision.mkdir(parents=True)
    runtime = revision / "runtime"
    runtime.mkdir()
    for original in (Path(__file__), exporter):
        shutil.copyfile(original, runtime / original.name)
        (runtime / original.name).chmod(0o444)
    targets = []
    view = revision / "canonical_view"
    (view / "evaluation_only").mkdir(parents=True)
    for name in ("protocol.json", "runs"):
        (view / name).symlink_to(root / name)
    for name in ("dev.annotations.json", "test.annotations.json", "review-sample.json"):
        (view / "evaluation_only" / name).symlink_to(root / "evaluation_only" / name)
    (view / "reports").mkdir()
    for split in ("dev", "test"):
        (view / "reports" / f"{split}-mechanism-report.json").symlink_to(root / "reports" / f"{split}-mechanism-report.json")
    for stage in ("scores", "regrades"):
        for old in sorted((root / "evaluation_only" / stage).rglob("score.json")):
            relative = old.relative_to(root / "evaluation_only" / stage)
            record = core.load(old)
            failed = record["status"] == "unknown" and record.get("error") == "judge_transport_exhausted; unknown retained"
            link = view / "evaluation_only" / stage / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            if failed:
                failed_label = "judge-1" if (old.parent / "judge-0.json").exists() else "judge-0"
                request_file = old.parent / (failed_label + ".attempt-0.json")
                request_hash = core.load(request_file)["request_sha256"]
                targets.append({"stage": stage, "relative": str(relative), "original_score_sha256": core.sha(old),
                                "original_request_sha256": request_hash, "original_failed_label": failed_label,
                                "successful_responses_sha256": {p.name: core.sha(p) for p in old.parent.glob("judge-?.json")}})
                link.symlink_to(revision / stage / relative)
            else:
                link.symlink_to(old)
    protocol = {"schema": "same-request-transport-recovery-v1", "date": "2026-10-12",
                "parent_protocol_sha256": core.sha(root / "protocol.json"), "judge_model": "qwen3-8b",
                "registration": "execution amendment after original completed run; not original preregistered execution",
                "targets": targets, "workers": 3, "additional_transport_attempts_per_request": 3,
                "maximum_original_plus_recovery_attempts_per_request": 6,
                "original_quality_schema_attempts": 2, "quality_retry": False,
                "changes": "transport recovery only; original model, requests, grading and statistical functions reused",
                "parent_scores_preserved": True, "failed_request_usage": "unknown; never imputed",
                "network_circuit": "stop scheduling on first recovery slot with exhausted transport attempts"}
    core.save(revision / "protocol.json", protocol)
    core.save(revision / "seal.json", {"protocol_sha256": core.sha(revision / "protocol.json"),
                                     "runtime": {p.name: core.sha(p) for p in runtime.iterdir()}})
    (revision / "protocol.json").chmod(0o444)
    (revision / "seal.json").chmod(0o444)
    print(core.wire({"targets": len(targets), "revision": str(revision), "api_calls": 0}))


def run(core, evaluation, root, revision, plot_python):
    core.verify(root)
    seal = core.load(revision / "seal.json")
    if core.sha(revision / "protocol.json") != seal["protocol_sha256"]:
        raise ValueError("recovery protocol drift")
    for name, digest in seal["runtime"].items():
        if core.sha(revision / "runtime" / name) != digest:
            raise ValueError("recovery runtime drift")
    spec = core.load(revision / "protocol.json")
    if spec["parent_protocol_sha256"] != core.sha(root / "protocol.json"):
        raise ValueError("recovery parent drift")
    parent = core.load(root / "protocol.json")
    annotations = {split: evaluation.annotation_map(root, split) for split in ("dev", "test")}
    provider = core.Provider(root, root / "local_private/.env.qwen_proxy")
    circuit = threading.Event()
    with (revision / "campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status(revision, {"state": "running", "phase": "health", "targets": len(spec["targets"])})
        health = provider(core.request([{"role": "system", "content": '只输出JSON {"ok":true}。'},
                                        {"role": "user", "content": "验证接口可用。"}], "grep", final=True, output_tokens=30),
                          revision / "health", "probe")
        core.usage(health)
        if health["choices"][0]["finish_reason"] != "stop" or json.loads(health["choices"][0]["message"]["content"]) != {"ok": True}:
            raise RuntimeError("transport health probe failed; no bulk requests")
        status(revision, {"state": "running", "phase": "same_request_recovery", "targets": len(spec["targets"])})

        def one(target):
            stage = target["stage"]
            relative = Path(target["relative"])
            destination = revision / stage / relative
            if destination.exists():
                record = core.load(destination)
                if record["transport_recovery_sha256"] != seal["protocol_sha256"]:
                    raise ValueError("recovery score binding drift")
                return
            if circuit.is_set():
                raise RuntimeError("network recovery circuit open; preserve partial outputs")
            split, qid, repeat, arm = relative.parts[:4]
            original = root / "evaluation_only" / stage / relative
            if core.sha(original) != target["original_score_sha256"]:
                raise ValueError("original scoring record drift")
            session_path = root / "runs" / split / qid / repeat / arm / "session.json"
            session = core.load(session_path)
            original_request = core.load(original.parent / (target["original_failed_label"] + ".attempt-0.json"))["request"]
            if original_request["model"] != "qwen3-8b":
                raise ValueError("original judge model mismatch")

            def fetch(req, folder, label):
                if (original.parent / (label + ".json")).exists():
                    if core.sha(original.parent / (label + ".json")) != target["successful_responses_sha256"][label + ".json"]:
                        raise ValueError("original successful response drift")
                    return provider(req, original.parent, label)  # 只重放已收到的格式无效响应，不重生成。
                if label == target["original_failed_label"]:
                    import hashlib
                    digest = hashlib.sha256(core.wire(req).encode()).hexdigest()
                    if digest != target["original_request_sha256"]:
                        raise ValueError("recovery first request differs from original request")
                try:
                    return provider(req, folder, label)
                except core.TransportFailure:
                    circuit.set()
                    raise

            result = evaluation.judge_session(root, parent, annotations[split][session["question"]["family_id"]],
                                              session, session_path, fetch, destination.parent)
            core.save(destination, {**result, "protocol_sha256": spec["parent_protocol_sha256"],
                                    "transport_recovery_sha256": seal["protocol_sha256"],
                                    "original_score_sha256": target["original_score_sha256"]})
            print(core.wire({"stage": stage, "split": split, "question": qid, "repeat": repeat, "arm": arm, "score_status": result["status"]}), flush=True)

        with ThreadPoolExecutor(max_workers=spec["workers"]) as pool:
            list(pool.map(one, spec["targets"]))
        if circuit.is_set():
            raise RuntimeError("network recovery attempts exhausted in at least one slot")
        for split in ("dev", "test"):
            report = evaluation.report(revision / "canonical_view", parent, split)
            report["transport_recovery"] = {"protocol": str(revision / "protocol.json"), "sha256": seal["protocol_sha256"],
                                             "registration": spec["registration"], "judge_model": "qwen3-8b"}
            core.save(revision / "canonical_view/reports" / f"{split}-report.json", report)
            with (revision / f"{split}_export.log").open("a") as log:
                code = subprocess.run([str(plot_python.absolute()), str(revision / "runtime/build_report.py"),
                                       "--root", str(revision / "canonical_view"), "--split", split,
                                       "--output", str(revision / "derived/exports_001" / split)],
                                      stdout=log, stderr=subprocess.STDOUT,
                                      env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}).returncode
            if code:
                raise RuntimeError("recovery export failed; preserve output")
        status(revision, {"state": "complete", "phase": "finished", "targets": len(spec["targets"]),
                          "transport_recovery_sha256": seal["protocol_sha256"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument("--exporter", type=Path)
    parser.add_argument("--plot-python", type=Path)
    args = parser.parse_args()
    root, revision = args.root.resolve(), args.revision.resolve()
    sys.path.insert(0, str(root / "runtime"))
    import chapter2_augmentation as core
    import chapter2_augmentation_evaluation as evaluation
    if args.command == "prepare":
        if not args.exporter:
            parser.error("prepare needs frozen exporter source")
        prepare(core, root, revision, args.exporter)
    else:
        if Path(__file__).resolve() != revision / "runtime" / Path(__file__).name or not args.plot_python:
            raise ValueError("execute archived recovery script with plot Python")
        try:
            run(core, evaluation, root, revision, args.plot_python)
        except Exception as exc:
            status(revision, {"state": "failed", "phase": "see_campaign_log", "error_type": type(exc).__name__})
            raise


if __name__ == "__main__":
    main()
