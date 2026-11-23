# Read-only dependency materialization for the chapter 3 runtime.
"""Materialize a chapter-owned installed DSH dependency closure, without Git/npm.

Source packages are read only. Junctions in the output point only inside the
snapshot. This copies installed bytes, not a verified upstream commit.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat


def sha(path):
    result=hashlib.sha256()
    with long_path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def long_path(path):
    path = Path(path).absolute()
    return Path("\\\\?\\" + str(path)) if os.name == "nt" and not str(path).startswith("\\\\?\\") else path


def resolve_package(anchor, name):
    for base in [anchor, *anchor.parents]:
        p = base / "node_modules" / name
        if (p / "package.json").is_file():
            return p.resolve()
    return None


def snapshot(source: Path, target: Path, resume=False):
    source, target = source.resolve(), target.resolve()
    if (target.exists() and not resume) or target == source or source in target.parents:
        raise ValueError("snapshot must be a new directory outside upstream")
    queue = [source / "apps/cli"]
    packages, edges, missing = {}, [], []
    while queue:
        package = queue.pop().resolve()
        if package in packages:
            continue
        package.relative_to(source)
        manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
        packages[package] = manifest
        dependencies = set(manifest.get("dependencies", {}))
        optional = set(manifest.get("optionalDependencies", {}))
        peers = set(manifest.get("peerDependencies", {}))
        for name in sorted(dependencies | optional | peers):
            resolved = resolve_package(package, name)
            if resolved is None:
                if name in dependencies and name not in optional:
                    raise ValueError(f"missing installed dependency: {manifest['name']} -> {name}")
                missing.append([manifest["name"], name])
                continue
            resolved.relative_to(source)
            edges.append((package, name, resolved))
            queue.append(resolved)
    if (target / "snapshot.json").exists():
        raise ValueError("completed snapshots cannot be resumed or overwritten")
    target.mkdir(parents=True, exist_ok=resume)
    files = []
    excluded = {"node_modules", ".git", ".agents", ".claude", "tests", "test", "__tests__", ".cache"}
    for package in sorted(packages):
        for base, dirs, names in os.walk(package, followlinks=False):
            dirs[:] = [d for d in dirs if d not in excluded]
            for d in dirs:
                p = Path(base) / d
                if p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError(f"unexpected package directory link: {p}")
            for name in names:
                p = Path(base) / name
                if name == ".env" or name.startswith(".env."):
                    continue
                if p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError(f"unexpected package file link: {p}")
                rel = p.relative_to(source)
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                before = sha(p)
                if dest.exists():
                    if sha(dest) != before:
                        raise ValueError(f"partial copy mismatch: {rel}")
                else:
                    shutil.copyfile(long_path(p), long_path(dest))
                if before != sha(p) or before != sha(dest):
                    raise RuntimeError(f"source changed during snapshot: {rel}")
                files.append({"path": rel.as_posix(), "sha256": before})
    links = []
    import _winapi
    for package, name, resolved in edges:
        link = target / package.relative_to(source) / "node_modules" / name
        dest = target / resolved.relative_to(source)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() and link.resolve() != dest:
            # A denied CreateJunction can leave its empty directory behind.
            # Remove ONLY that empty directory, never recursively or by glob.
            if not resume or not link.resolve().is_relative_to(target) or any(link.iterdir()):
                raise ValueError(f"unexpected existing dependency path: {link}")
            link.rmdir()
        if not link.exists():
            _winapi.CreateJunction(str(dest), str(link))
        links.append({"path": link.relative_to(target).as_posix(), "target": dest.relative_to(target).as_posix()})
    result = {"schema": "chapter3_installed_snapshot_v1", "packages": [
        {"name": v["name"], "version": v.get("version"), "path": p.relative_to(source).as_posix()}
        for p, v in packages.items()], "files": files, "links": links, "uninstalled_optional_or_peers": missing}
    (target / "snapshot.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def verify(target: Path):
    target = target.resolve()
    manifest = json.loads((target / "snapshot.json").read_text(encoding="utf-8"))
    for row in manifest["files"]:
        p = target / row["path"]
        if not p.resolve().is_relative_to(target) or sha(p) != row["sha256"]:
            raise ValueError(f"snapshot file mismatch: {row['path']}")
    for row in manifest["links"]:
        expected = target / row["target"]
        if (target / row["path"]).resolve() != expected or not expected.is_relative_to(target):
            raise ValueError(f"snapshot link mismatch: {row['path']}")
    known_files = {r['path'] for r in manifest['files']} | {'snapshot.json'}
    known_links = {r['path'] for r in manifest['links']}
    for base, dirs, names in os.walk(target, followlinks=False):
        for name in dirs[:]:
            p = Path(base) / name
            if p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                if p.relative_to(target).as_posix() not in known_links:
                    raise ValueError(f"unlisted runtime link: {p}")
                dirs.remove(name)
        for name in names:
            p = Path(base) / name
            if p.relative_to(target).as_posix() not in known_files:
                raise ValueError(f"unlisted runtime file: {p}")
    return {"files_verified": len(manifest["files"]), "internal_links_verified": len(manifest["links"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--resume", action="store_true", help="verify and finish an incomplete owned copy; never overwrite bytes")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.target)))
    else:
        if args.source is None:
            parser.error("--source is required for creation")
        result = snapshot(args.source, args.target, args.resume)
        print(json.dumps({"packages": len(result["packages"]), "files": len(result["files"]), "links": len(result["links"])}))
