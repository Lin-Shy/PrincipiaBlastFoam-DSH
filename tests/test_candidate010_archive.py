import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import verify_candidate010_archive as verify


def test_archive_verifier_detects_drift(tmp_path):
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("frozen")
    manifest = {
        "frozen_graph_sha256": "graph",
        "artifacts": [{
            "path": "artifact.txt",
            "sha256": verify.sha256(artifact),
            "bytes": artifact.stat().st_size,
            "role": "archived_copy",
        }],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert verify.verify(tmp_path)["status"] == "passed"
    artifact.write_text("changed")
    result = verify.verify(tmp_path)
    assert result["status"] == "failed"
    assert result["failures"][0]["reason"] in {"size", "sha256"}
