"""Export the immutable query-time subset of a Principia construction graph."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


RUNTIME_KEYS = ("corpus_id", "nodes", "edges")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def export(source, output, manifest=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    manifest = Path(manifest).resolve() if manifest else output.with_suffix(
        output.suffix + ".manifest.json"
    )
    if output.exists() or manifest.exists():
        raise FileExistsError("runtime graph or manifest already exists")
    graph = json.loads(source.read_text())
    missing = [key for key in RUNTIME_KEYS if key not in graph]
    if missing:
        raise ValueError("construction graph missing: " + ", ".join(missing))
    if not isinstance(graph["nodes"], dict) or not isinstance(graph["edges"], list):
        raise ValueError("invalid graph nodes/edges")
    runtime = {key: graph[key] for key in RUNTIME_KEYS}
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=output.name + ".", suffix=".tmp", dir=output.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(runtime, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if "temporary" in locals() and Path(temporary).exists():
            Path(temporary).unlink()
    record = {
        "schema": "principia-runtime-graph-export-v1",
        "source_graph": os.path.relpath(source, manifest.parent),
        "source_graph_sha256": digest(source),
        "runtime_graph": os.path.relpath(output, manifest.parent),
        "runtime_graph_sha256": digest(output),
        "corpus_id": graph["corpus_id"],
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "retained_top_level_keys": list(RUNTIME_KEYS),
        "dropped_top_level_keys": sorted(set(graph) - set(RUNTIME_KEYS)),
        "semantic_statement": (
            "Node and edge records are byte-for-byte equivalent after JSON decoding; "
            "only query-unused top-level construction metadata is omitted."
        ),
        "external_index": False,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output, args.manifest), ensure_ascii=False))


if __name__ == "__main__":
    main()
