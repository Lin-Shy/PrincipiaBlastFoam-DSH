"""Read-only provenance and packaging audit of seven frozen cavity attempts."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

WORKSPACE = Path(__file__).resolve().parents[5]
BASE = WORKSPACE / "graduation-experiment-results/chapter3_end_to_end_evaluation/dsh"
OUT = BASE / "delivery_contract_audit_20261122"
CASES = [
    ("provided-cavity", "professional", "openfoam_cavity_agent50_20261122", "professional", True),
    ("CAVITY-MOD-02", "general", "openfoam_cavity_pair100_20261122/general", "general", True),
    ("CAVITY-MOD-02", "professional", "openfoam_cavity_pair100_20261122/professional", "professional", False),
    ("CAVITY-MOD-03", "old", "openfoam_cavity_revision100_20261122/old", "professional", False),
    ("CAVITY-MOD-03", "revised", "openfoam_cavity_revision100_20261122/revised", "professional", False),
    ("CAVITY-MOD-04", "on", "delivery_controls_live100_20261122/on", "professional", False),
    ("CAVITY-MOD-04", "off", "delivery_controls_live100_20261122/off", "professional", False),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(raw):
    return raw.replace(b"\r\n", b"\n")


def main(output=OUT):
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for task, variant, parent_name, arm, historical_pass in CASES:
        parent = BASE / parent_name
        root = parent / arm
        request_path = root / "workspace/exchange/request.json"
        request = json.loads(request_path.read_bytes())
        seal = json.loads((root / "sealed.json").read_bytes())
        receipt = json.loads((root / "workspace/exchange/receipt.json").read_bytes())
        terminal = json.loads((parent / "terminal.json").read_bytes())
        assert digest(root / "submission.zip") == seal["archive_sha256"]
        staged = {name: normalize((parent / "payload/case" / name).read_bytes()) == normalize(text.encode()) for name, text in request.items()}
        workspace_inputs = {name: normalize((root / "workspace/case" / name).read_bytes()) == normalize(text.encode()) for name, text in request.items()}
        native_changed = [name for name, text in request.items() if normalize((root / "workspace/exchange/native/case" / name).read_bytes()) != normalize(text.encode())]
        receipt_is_native = all(digest(root / "workspace/exchange/native" / name) == value for name, value in receipt["files"].items())
        with zipfile.ZipFile(root / "submission.zip") as archive:
            members = archive.namelist()
            required = ["case/" + name for name in request] + ["README.md", "postprocess.py", "summary.json", "receipt.json"]
            submitted_match = {name: normalize(archive.read("case/" + name)) == normalize(text.encode()) for name, text in request.items() if "case/" + name in members}
            root_inputs = {name: normalize(archive.read(name)) == normalize(text.encode()) for name, text in request.items() if name in members}
            initial_backup = [name for name in members if name.startswith("case_original/")]
            native_replacements = [name for name, matches in submitted_match.items() if not matches and archive.read("case/" + name) == (root / "workspace/exchange/native/case" / name).read_bytes()]
            delivery = root / "workspace/delivery"
            workspace_members = sorted(p.relative_to(delivery).as_posix() for p in delivery.rglob("*") if p.is_file())
            packager_preserves_tree = sorted(members) == workspace_members and all(archive.read(name) == (delivery / name).read_bytes() for name in members)
        task_path = root / "workspace/TASK.md"
        task_text = task_path.read_text(encoding="utf8")
        delivery_line = next(line for line in task_text.splitlines() if "自行在 delivery/" in line)
        rows.append(dict(task=task, variant=variant, source=str(root.relative_to(WORKSPACE)), historical_pass=historical_pass,
            requests=seal["requests"], tokens_reported=seal["tokens_reported"],
            job=terminal["JobId"], node_completed=terminal["JobState"] == "COMPLETED" and terminal["ExitCode"] == "0:0",
            task_sha256=digest(task_path), public_delivery_clause=delivery_line,
            task_explicit_normalized_text_identity=any(term in task_text for term in ("逐字", "归一换行", "CRLF", "normalized-byte")),
            request_sha256=digest(request_path), submission_sha256=seal["archive_sha256"],
            staged_inputs_match_registered=staged, workspace_inputs_still_match_registered=workspace_inputs,
            native_input_files_changed_after_execution=native_changed, receipt_files_hashes_are_native=receipt_is_native,
            missing_required_paths=[name for name in required if name not in members],
            delivered_inputs_match_registered=submitted_match, misplaced_root_inputs_match_registered=root_inputs,
            delivered_inputs_replaced_by_native=native_replacements, initial_backup_members=initial_backup,
            README_present="README.md" in members, postprocessor_present="postprocess.py" in members,
            packager_preserves_current_delivery_paths_and_bytes=packager_preserves_tree))
    record = dict(scope="Retrospective maintenance audit, not regrading or a new independent task set",
        historical_attempts=len(rows), task_identities=4, shared_public_source_family="provided cavity modification",
        new_model_requests=0, new_node_jobs=0, historical_requests=sum(r["requests"] for r in rows),
        historical_tokens_reported=sum(r["tokens_reported"] for r in rows), rows=rows,
        audit_source_sha256=digest(Path(__file__)))
    with (output / "findings.json").open("x", encoding="utf8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"attempts": len(rows), "historical_requests": record["historical_requests"],
        "all_staged_match": all(all(r["staged_inputs_match_registered"].values()) for r in rows),
        "all_workspace_inputs_preserved": all(all(r["workspace_inputs_still_match_registered"].values()) for r in rows),
        "all_packaging_matches": all(r["packager_preserves_current_delivery_paths_and_bytes"] for r in rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT, help="A new output directory; existing findings are never overwritten")
    main(parser.parse_args().output)
