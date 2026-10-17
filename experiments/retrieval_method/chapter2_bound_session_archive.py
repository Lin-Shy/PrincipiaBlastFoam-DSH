"""Archive immutable, bound generation sessions without stopping a live controller.

Only folders with a verified result-binding are eligible. Operational journals,
unbound/inflight folders, quality scores and model calls are outside this utility.
Earlier manifests form a disjoint, byte-verified delta chain. ZIP parts are bounded
by uncompressed input size and independently read back before publication.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_prior(root: Path, manifests: list[Path]):
    files, dependencies = {}, {}
    for path in manifests:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        data = path.read_bytes()
        dependencies[relative] = digest(data)
        for name, expected in json.loads(data)["files_sha256"].items():
            target = (root / name).resolve()
            target.relative_to(root.resolve())
            if name in files:
                raise ValueError("Overlapping archive deltas")
            if digest(target.read_bytes()) != expected:
                raise ValueError("Previously archived original changed")
            files[name] = expected
    return files, dependencies


def collect_bound(root: Path, generation: Path):
    files, sessions = {}, []
    protocols = {}
    for name in ["protocol.json", "diagnostic-protocol.json"]:
        protocol = generation / name
        if protocol.exists():
            protocols[digest(protocol.read_bytes())] = protocol
    # Snapshot the binding list once. Subsequent completions wait for a later delta.
    bindings = sorted(generation.glob("**/sessions/*/result-binding.json"))
    for path in bindings:
        folder = path.parent
        binding_bytes = path.read_bytes()
        binding = json.loads(binding_bytes)
        result_bytes = (folder / "result.json").read_bytes()
        result = json.loads(result_bytes)
        cell_id = folder.parent.parent.relative_to(generation).as_posix()
        if not isinstance(result, dict) or not {"protocol_sha256", "formal_cell_id", "formal_result"} <= result.keys():
            raise ValueError("Invalid terminal result structure")
        if binding != dict(result_sha256=digest(result_bytes),
                           protocol_sha256=result["protocol_sha256"], cell_id=cell_id):
            raise ValueError("Invalid terminal result binding")
        if result["formal_cell_id"] != cell_id or result["formal_result"] is not True:
            raise ValueError("Invalid formal session identity")
        protocol = protocols.get(binding["protocol_sha256"])
        if protocol is None:
            raise ValueError("Changed formal protocol")
        files[protocol.relative_to(root).as_posix()] = digest(protocol.read_bytes())
        for item in sorted(folder.rglob("*")):
            if not item.is_file():
                continue
            item.resolve().relative_to(root.resolve())
            files[item.relative_to(root).as_posix()] = digest(item.read_bytes())
        # Recheck the publication barrier after reading the whole session folder.
        if path.read_bytes() != binding_bytes or (folder / "result.json").read_bytes() != result_bytes:
            raise ValueError("Bound result changed during snapshot")
        sessions.append(dict(folder=folder.relative_to(root).as_posix(),
                             binding_sha256=digest(binding_bytes), result_sha256=digest(result_bytes)))
    return files, sessions


def write_parts(root: Path, output: Path, files: dict[str, str], limit: int):
    if limit <= 0:
        raise ValueError("Positive part input limit required")
    parts, batch, size = [], [], 0

    def flush():
        if not batch:
            return
        target = output / f"bound-session-delta-{len(parts)+1:03d}.zip"
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in batch:
                data = (root / name).read_bytes()
                if digest(data) != files[name]:
                    raise ValueError("Snapshot input changed before archive write")
                archive.writestr(name, data)
        with zipfile.ZipFile(target) as archive:
            if archive.namelist() != batch:
                raise ValueError("ZIP membership changed")
            for name in batch:
                if digest(archive.read(name)) != files[name]:
                    raise ValueError("ZIP readback differs")
                if digest((root / name).read_bytes()) != files[name]:
                    raise ValueError("Snapshot original changed after archive write")
        parts.append(dict(path=target.name, sha256=digest(target.read_bytes()),
                          zip_bytes=target.stat().st_size, source_bytes=size, files=list(batch)))

    for name in sorted(files):
        amount = (root / name).stat().st_size
        if amount > limit:
            raise ValueError("Single input exceeds configured ZIP part limit")
        if batch and size + amount > limit:
            flush()
            batch, size = [], 0
        batch.append(name)
        size += amount
    flush()
    return parts


def archive_bound(root: Path, output: Path, manifests: list[Path], *, part_source_limit=64*1024*1024):
    root, output = root.resolve(), output.resolve()
    output.relative_to(root)
    if output.exists():
        raise FileExistsError("New immutable archive directory required")
    prior, dependencies = load_prior(root, manifests)
    current, sessions = collect_bound(root, root / "formal/generation_001")
    for name in prior.keys() & current.keys():
        if prior[name] != current[name]:
            raise ValueError("Bound snapshot diverges from earlier archive")
    delta = {name: expected for name, expected in current.items() if name not in prior}
    if not delta:
        raise ValueError("No new bound session files")
    output.mkdir(parents=True, exist_ok=False)
    parts = write_parts(root, output, delta, part_source_limit)
    record = dict(schema="bound_generation_session_delta_archive_v1",
                  created_utc=datetime.now(timezone.utc).isoformat(),
                  scope="Bound terminal session snapshot during generation; excludes inflight and mutable controller files. Not complete activity.",
                  terminal_sessions_in_snapshot=len(sessions), session_bindings=sessions,
                  requires_manifests_sha256=dependencies, files_sha256=delta,
                  source_bytes=sum(p["source_bytes"] for p in parts),
                  parts=parts, readback_verified=True, local_originals_retained=True,
                  inflight_sessions_included=False, mutable_execution_journals_included=False,
                  model_calls=0, quality_scores_read=False,
                  union_archived_files=len(prior)+len(delta), part_source_limit=part_source_limit)
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
    shutil.copy2(__file__, output / "archive-source.py")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-manifest", type=Path, action="append", default=[])
    args = parser.parse_args()
    record = archive_bound(args.root, args.output, args.prior_manifest)
    print({k: record[k] for k in ["terminal_sessions_in_snapshot", "union_archived_files", "source_bytes", "readback_verified", "model_calls"]}, flush=True)


if __name__ == "__main__":
    main()
