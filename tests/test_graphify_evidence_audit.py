from pathlib import Path
import json

import pytest

from experiments.retrieval_method.graphify_evidence_audit import audit, sha


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_primary_file_coverage_is_not_fact_or_relation_accuracy(tmp_path):
    paths = ("manual/m.md", "tutorials/a/settings")
    annotation = {"id": "Q", "category": "cross", "evidence": [
        {"id": str(i), "path": path, "start": 1, "end": 1, "quote": "entry 1;", "sha256": sha(b"entry 1;\n")}
        for i, path in enumerate(paths)]}
    write(tmp_path/"control/evaluation_only/annotations.json", [annotation])
    for variant in ("native", "text_adapter"):
        root = tmp_path/variant
        write(root/"path-map.json", {"manual/m.md": paths[0], "tutorials/a/settings.txt": paths[1]})
        for path in paths:
            source = root/"skill/corpus"/path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("entry 1;\n")
        nodes = [{"id": "m", "label": "Unrelated chapter concept", "source_file": paths[0]},
                 {"id": "s", "label": "Generic file", "source_file": "tutorials/a/settings.txt"}]
        write(root/"graphify-out/graph.json", {"nodes": nodes, "links": [{"source": "m", "target": "s", "confidence": "INFERRED"}]})
    write(tmp_path/"protocol.json", {"files": {}})
    output = tmp_path/"audit.json"
    audit(tmp_path, output)
    result = json.loads(output.read_text())
    assert result["model_calls"] == 0
    assert "not_quality_score" in result["purpose"]
    row = result["items"][0]
    assert row["all_evidence_files_have_primary_nodes"]
    assert row["evidence"][0]["nodes"][0]["source_location"] is None
    assert row["direct_cross_source_edges_between_required_files"][0]["confidence"] == "INFERRED"
    assert "fact" in row["evidence"][0]["note"]
    with pytest.raises(FileExistsError):
        audit(tmp_path, output)


def test_audit_rejects_frozen_source_change(tmp_path):
    write(tmp_path/"protocol.json", {"files": {"source": sha(b"old")}})
    (tmp_path/"source").write_text("changed")
    with pytest.raises(ValueError, match="Frozen artifact"):
        audit(tmp_path, tmp_path/"audit.json")
