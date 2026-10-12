import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import export_runtime_graph as runtime


def test_runtime_export_keeps_only_query_required_graph_fields(tmp_path):
    source = tmp_path / "construction.json"
    source.write_text(json.dumps({
        "corpus_id": "fixture",
        "nodes": {"n": {"id": "n", "path": "a"}},
        "edges": [],
        "candidates": [{"unused": True}],
        "issues": ["construction-only"],
    }))
    output = tmp_path / "runtime.json"

    manifest = runtime.export(source, output)

    assert json.loads(output.read_text()) == {
        "corpus_id": "fixture",
        "nodes": {"n": {"id": "n", "path": "a"}},
        "edges": [],
    }
    assert manifest["external_index"] is False
    assert manifest["dropped_top_level_keys"] == ["candidates", "issues"]
    assert runtime.digest(output) == manifest["runtime_graph_sha256"]

    with pytest.raises(FileExistsError):
        runtime.export(source, output)
