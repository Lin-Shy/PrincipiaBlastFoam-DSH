"""Probe candidate 010's generic claim-local citation verifier on frozen dev drafts.

The probe never sends gold, review decisions, method identity, or quality scores
to the model.  Development-set quality is used only to select the already
observed class "content correct but strict support failed"; every selected
draft is then rechecked against its own exact, previously seen citation text.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import candidate_qa as candidate
import graphify_qa as transport
import leaderboard_audit as audit
import natural_index_free_leaderboard as leaderboard
import navigation_qa as qa


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select(quality: dict) -> list[dict]:
    arm = next(row for row in quality["arms"] if row["arm"] == "principia_index_free")
    return [
        {"session": row["session"], "family": row["family"], "question_id": row["question_id"]}
        for row in arm["sessions"]
        if row["quality"].get("answer_accuracy") == 1
        and not row["quality"].get("qa_success")
        and row["quality"].get("citation_accuracy") is not None
        and row["quality"]["citation_accuracy"] < 1
    ]


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--run", type=Path, required=True)
    cli.add_argument("--quality", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--key-file", type=Path)
    cli.add_argument("--settings-file", type=Path)
    args = cli.parse_args()
    run, quality_path, output = args.run.resolve(), args.quality.resolve(), args.output.resolve()
    quality = audit.read(quality_path)
    selected = select(quality)
    if len({row["family"] for row in selected}) < 2:
        raise ValueError("candidate 010 requires a generic defect spanning at least two families")
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = output / "protocol.json"
    bindings = []
    for row in selected:
        folder = run / "principia_index_free" / "sessions" / row["session"]
        bindings.append({**row, "result_sha256": sha(folder / "result.json"),
                         "draft_response_sha256": sha(folder / "final.json")})
    protocol = {
        "schema": "candidate-010-claim-verification-probe-v1",
        "model": qa.MODEL,
        "selection": "dev answers with answer_accuracy=1, qa_success=false and citation_accuracy<1",
        "model_payload_excludes": ["gold", "quality", "review decisions", "method identity", "family"],
        "mechanism": "claim-local exact citation packet; no evidence from catalogs, other claims or memory",
        "budgets_changed": False,
        "dataset_changed": False,
        "graph_changed": False,
        "evaluation_protocol_changed": False,
        "run_protocol_sha256": sha(run / "protocol.json"),
        "quality_sha256": sha(quality_path),
        "candidate_qa_sha256": sha(Path(candidate.__file__)),
        "bindings": bindings,
    }
    if protocol_path.exists() and audit.read(protocol_path) != protocol:
        raise ValueError("probe protocol drift")
    audit.save(protocol_path, protocol)
    transport.SECRET = leaderboard.read_secret(args.key_file, args.settings_file)
    transport.reset_transport_circuit()
    results = []
    for row in bindings:
        source = run / "principia_index_free" / "sessions" / row["session"]
        result = audit.read(source / "result.json")
        draft = candidate.decode(qa.choice(audit.read(source / "final.json")))
        packet = candidate.claim_evidence_packet(draft, result["seen_lines"])
        request_text = candidate.VERIFY + "\nanswer_draft: " + qa.wire(draft) + "\nclaim_evidence_packet: " + qa.wire(packet)
        body = qa.request([
            {"role": "system", "content": "Only audit the supplied draft against its claim-local quoted evidence. Return the required JSON."},
            {"role": "user", "content": request_text},
        ])
        folder = output / "sessions" / row["session"]
        response = transport.fetch(folder, "claim-check", body, transport.SECRET or None)
        choice = qa.choice(response)
        verification = candidate.decode(choice)
        released, complete = candidate.release_verified(draft, verification, result["seen_lines"])
        votes = verification.get("claims", []) if isinstance(verification, dict) else []
        rejected = [vote.get("index") for vote in votes if isinstance(vote, dict) and vote.get("supported") is False]
        record = {**row, "complete": complete, "draft_claims": len(draft.get("claims", [])),
                  "released_claims": len(released.get("references", [])), "rejected_claim_indices": rejected,
                  "verification": verification, "released": released,
                  "provider_model": response["raw_response"].get("model"),
                  "request_sha256": response["request_sha256"]}
        audit.save(folder / "result.json", record)
        results.append(record)
        print("PROBED", row["session"], "rejected", len(rejected), flush=True)
    rejected_families = sorted({row["family"] for row in results if row["rejected_claim_indices"]})
    summary = {
        "schema": "candidate-010-claim-verification-probe-summary-v1",
        "protocol_sha256": sha(protocol_path),
        "selected": len(results),
        "families": len({row["family"] for row in results}),
        "complete": sum(row["complete"] for row in results),
        "provider_models": dict(Counter(row["provider_model"] for row in results)),
        "answers_with_rejected_claims": sum(bool(row["rejected_claim_indices"]) for row in results),
        "rejected_families": rejected_families,
        "passed": all(row["complete"] for row in results)
        and set(row["provider_model"] for row in results) == {qa.MODEL}
        and len(rejected_families) >= 2,
        "interpretation": "mechanism probe only; not a quality score or substitute for a fresh four-arm run",
    }
    audit.save(output / "summary.json", summary)
    print(qa.wire(summary))


if __name__ == "__main__":
    main()
