"""Complete failed case-alias chunks by inheriting successes and splitting gaps."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
from pathlib import Path
import shutil

import candidate_case_aliases as base
import graphify_qa as transport
import navigation_qa as qa


def prepare(parent, output, entities_per_chunk=30):
    if output.exists():
        raise FileExistsError("preserve alias completion")
    protocol = base.verify(parent)
    parent_chunks = qa.read(parent / "chunks.json")
    parent_layer = qa.read(parent / "layer.json")
    if parent_layer.get("complete") or set(parent_layer.get("missing_chunks", [])) != {
            identity for identity in parent_chunks
            if not (parent / "sessions" / identity / "validated.json").exists()}:
        raise ValueError("parent alias gap identity mismatch")
    inherited, children = {}, {}
    for identity, chunk in parent_chunks.items():
        valid = parent / "sessions" / identity / "validated.json"
        if valid.exists():
            inherited[identity] = {"path": str(valid.resolve()),
                "sha256": base.digest(valid.read_bytes()), "chunk": chunk}
            continue
        entities = chunk["entities"]
        for offset in range(0, len(entities), entities_per_chunk):
            selected = entities[offset:offset + entities_per_chunk]
            child_id = base.digest([protocol["corpus_id"], "alias-completion",
                identity, offset, [entity["node_id"] for entity in selected]])[:24]
            children[child_id] = {"id": child_id, "parent_chunk": identity,
                "case_directory": chunk["case_directory"],
                "same_case_readme": chunk.get("same_case_readme", ""), "entities": selected}
    output.mkdir(parents=True)
    for name in ("candidate_case_alias_completion.py", "candidate_case_aliases.py",
                 "graphify_qa.py", "navigation_qa.py", "graphify_query_backend.py"):
        shutil.copy2(Path(__file__).with_name(name), output / name)
    qa.write(output / "chunks.json", children);qa.write(output / "inherited.json", inherited)
    files = {p.name: base.digest(p.read_bytes()) for p in output.iterdir() if p.is_file()}
    copied = {key: value for key, value in protocol.items() if key != "files"}
    copied.update(schema="candidate-case-alias-completion-v1",
        parent_root=str(parent.resolve()),
        parent_protocol_sha256=base.digest((parent / "protocol.json").read_bytes()),
        parent_layer_sha256=base.digest((parent / "layer.json").read_bytes()),
        selection="all and only missing parent chunks, split mechanically; no question/gold input",
        entities_per_chunk=entities_per_chunk, inherited_chunks=len(inherited),
        completion_chunks=len(children), files=files)
    qa.write(output / "protocol.json", copied)
    print(qa.wire({"inherited": len(inherited), "parent_missing": len(parent_layer["missing_chunks"]),
                   "completion_chunks": len(children),
                   "completion_entities": sum(len(chunk["entities"]) for chunk in children.values())}))


def verify(output):
    protocol = qa.read(output / "protocol.json")
    if protocol.get("model") != "deepseek-flash" or qa.MODEL != "deepseek-flash":
        raise ValueError("alias completion model drift")
    for name, expected in protocol["files"].items():
        if base.digest((output / name).read_bytes()) != expected:
            raise ValueError("frozen alias completion input changed: " + name)
    parent = Path(protocol["parent_root"])
    if (base.digest((parent / "protocol.json").read_bytes()) != protocol["parent_protocol_sha256"]
            or base.digest((parent / "layer.json").read_bytes()) != protocol["parent_layer_sha256"]):
        raise ValueError("alias completion parent changed")
    return protocol


def compile_layer(output, protocol):
    parent = Path(protocol["parent_root"]);parent_chunks = qa.read(parent / "chunks.json")
    inherited, children = qa.read(output / "inherited.json"), qa.read(output / "chunks.json")
    records, missing, covered = [], [], {}
    for identity, item in inherited.items():
        path = Path(item["path"])
        if base.digest(path.read_bytes()) != item["sha256"]:
            raise ValueError("inherited alias result changed")
        records.append(qa.read(path));covered[identity] = [e["node_id"] for e in item["chunk"]["entities"]]
    for identity, chunk in children.items():
        path = output / "sessions" / identity / "validated.json"
        if path.exists():
            records.append(qa.read(path))
            covered.setdefault(chunk["parent_chunk"], []).extend(e["node_id"] for e in chunk["entities"])
        else:
            missing.append(identity)
    if not missing:
        for identity, chunk in parent_chunks.items():
            expected = [e["node_id"] for e in chunk["entities"]]
            if sorted(covered.get(identity, [])) != sorted(expected):
                raise ValueError("completion entity coverage gap or overlap")
    aliases = {}
    for record in records:
        for row in record["accepted"]:
            aliases.setdefault(row["node_id"], []).append({key: row[key] for key in
                ("text", "language", "reason", "verification_reason")})
    layer = {"schema": protocol["schema"],
        "protocol_sha256": base.digest((output / "protocol.json").read_bytes()),
        "corpus_id": protocol["corpus_id"], "parent_graph_sha256": protocol["graph_sha256"],
        "complete": not missing, "missing_chunks": missing, "records": len(records),
        "accepted_aliases": sum(len(rows) for rows in aliases.values()), "aliases": aliases,
        "gold_or_questions_used": False, "alias_status": protocol["alias_status"],
        "provenance": "hash-verified parent successes plus all missing chunks mechanically split"}
    qa.write(output / "layer.json", layer);return layer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "compile"))
    parser.add_argument("--parent", type=Path);parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path);parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--entities-per-chunk", type=int, default=30)
    args = parser.parse_args();output = args.output.resolve()
    if args.command == "prepare":
        prepare(args.parent.resolve(), output, args.entities_per_chunk);return
    protocol = verify(output)
    if args.command == "compile":
        print(qa.wire(compile_layer(output, protocol)));return
    if Path(__file__).resolve() != output / "candidate_case_alias_completion.py":
        raise ValueError("execute frozen alias completion runner")
    transport.SECRET = args.key_file.read_text().strip() if args.key_file else ""
    chunks = qa.read(output / "chunks.json")
    with (output / "runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = {pool.submit(base.process, output, chunk, protocol): identity
                    for identity, chunk in chunks.items()}
            for future in as_completed(jobs):
                identity = jobs[future]
                try:
                    result = future.result();print("DONE", identity, len(result["accepted"]), flush=True)
                except Exception as error:
                    qa.write(output / "sessions" / identity / "failure.json",
                             {"type": type(error).__name__, "reason": str(error)[:240]})
                    print("ERROR", identity, type(error).__name__, flush=True)
        layer = compile_layer(output, protocol)
        print(qa.wire({key: layer[key] for key in ("complete", "records", "accepted_aliases")}))


if __name__ == "__main__":
    main()
