"""审计并清除可再生Python缓存；内容副本仅列出，不据大小删除冻结文件。"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit(roots, output, apply=False, duplicates=False):
    roots = [Path(r).resolve() for r in roots]
    candidates = []
    for root in roots:
        for path in root.rglob("*.pyc"):
            if path.is_symlink() or "__pycache__" not in path.parts or not path.is_file():
                continue
            # 缓存对应.py必须存在，否则可能是仅存的可执行证据。
            source = path.parent.parent / (path.name.split(".cpython-", 1)[0] + ".py")
            if not source.is_file():
                continue
            candidates.append({"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size,
                               "source": str(source), "source_sha256": digest(source)})
    references = defaultdict(list)
    by_hash, by_name = defaultdict(list), defaultdict(list)
    for item in candidates:
        by_hash[item["sha256"]].append(item["path"])
        by_name[Path(item["path"]).name].append(item["path"])
    # C实现固定串批量匹配，避免在含长base64的历史响应上逐候选扫描。
    if candidates:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as patterns:
            patterns.write("\n".join(sorted(set(by_hash) | set(by_name))) + "\n")
            patterns.flush()
            result = subprocess.run(["rg", "--json", "--fixed-strings", "--file", patterns.name,
                  "--hidden", "--no-ignore", "-g", "*.json", "-g", "*.md", "-g", "*.py",
                  "-g", "*.tex", "-g", "*.sh", *map(str, roots)], capture_output=True, text=True)
            if result.returncode not in (0, 1):
                raise RuntimeError("reference scan failed; no cleanup performed")
            for line in result.stdout.splitlines():
                event = json.loads(line)
                if event["type"] != "match":
                    continue
                descriptor = event["data"]["path"]["text"]
                matched = set()
                for submatch in event["data"]["submatches"]:
                    key = submatch["match"]["text"]
                    matched.update(by_hash.get(key, []) + by_name.get(key, []))
                for path in matched:
                    references[path].append(descriptor)
    for item in candidates:
        item["references"] = references[item["path"]]
        item["action"] = "retain_bound_cache" if item["references"] else "remove_regenerable_cache"
    duplicate_groups = []
    if duplicates:
        sizes = defaultdict(list)
        for root in roots:
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts and path != Path(output):
                    size = path.stat().st_size
                    if size:
                        sizes[size].append(path)
        for size, paths in sizes.items():
            if len(paths) < 2:
                continue
            groups = defaultdict(list)
            for path in paths:
                groups[digest(path)].append(str(path))
            for sha, identical in groups.items():
                if len(identical) > 1:
                    duplicate_groups.append({"sha256": sha, "bytes_each": size, "paths": identical,
                                             "action": "retain_until_dependency_and_frozen_identity_verified"})
    report = {"schema": "chapter2-cleanup-audit-v1", "roots": list(map(str, roots)), "apply": apply,
              "candidates": candidates, "duplicate_groups": duplicate_groups,
              "removable_count": sum(i["action"] == "remove_regenerable_cache" for i in candidates),
              "removable_bytes": sum(i["bytes"] for i in candidates if i["action"] == "remove_regenerable_cache"),
              "policy": "only existing-source caches with no descriptor filename/hash binding; no deletion of frozen source/data/scores"}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # 删除前落盘清单，输出不可覆盖。
    with output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    if apply:
        outcomes = []
        for item in candidates:
            if item["action"] != "remove_regenerable_cache":
                continue
            path = Path(item["path"])
            if not path.exists():
                outcomes.append({"path": str(path), "action": "already_absent"})
                continue
            if digest(path) != item["sha256"] or digest(Path(item["source"])) != item["source_sha256"]:
                outcomes.append({"path": str(path), "action": "retain_changed_input"})
                continue
            path.unlink()
            outcomes.append({"path": str(path), "action": "removed", "bytes": item["bytes"]})
        for root in roots:
            for path in root.rglob("__pycache__"):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
        completion = {"audit_sha256": digest(output), "outcomes": outcomes,
                      "removed_count": sum(o["action"] == "removed" for o in outcomes),
                      "removed_bytes": sum(o.get("bytes", 0) for o in outcomes if o["action"] == "removed")}
        with output.with_suffix(".completion.json").open("x") as stream:
            json.dump(completion, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps({"audit": str(output), "removed_count": report["removable_count"] if apply else 0,
                      "removed_bytes": report["removable_bytes"] if apply else 0,
                      "retained_duplicate_groups": len(duplicate_groups)}, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--roots", nargs="+", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--duplicates", action="store_true")
    args = p.parse_args()
    audit(args.roots, args.output, args.apply, args.duplicates)
