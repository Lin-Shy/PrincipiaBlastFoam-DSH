import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import candidate_case_aliases as aliases


def test_alias_candidate_validation_rejects_unknown_node_and_bad_language():
    chunk = {"entities": [{"node_id": "n1"}]}
    good = {"entities": [{"node_id": "n1", "aliases": [
        {"text": "oxygen", "language": "en", "reason": "O2"}]}]}
    assert aliases.candidates(good, chunk)[0]["text"] == "oxygen"
    symbol = {"entities": [{"node_id": "n1", "aliases": [
        {"text": "γ", "language": "symbol", "reason": "gamma"}]}]}
    assert aliases.candidates(symbol, chunk)[0]["text"] == "γ"
    for bad in [
        {"entities": [{"node_id": "n2", "aliases": []}]},
        {"entities": [{"node_id": "n1", "aliases": [{"text": "oxygen", "language": "xx"}]}]},
    ]:
        try:
            aliases.candidates(bad, chunk)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid alias output must fail closed")


def test_apply_layer_only_adds_navigation_metadata(tmp_path):
    graph_path = tmp_path / "graph.json"
    graph = {"corpus_id": "c", "nodes": {"n1": {"id": "n1", "aliases": ["O2"]}}, "edges": []}
    graph_path.write_text(json.dumps(graph))
    layer_path = tmp_path / "layer.json"
    layer = {"complete": True, "corpus_id": "c", "parent_graph_sha256": aliases.digest(graph_path.read_bytes()),
             "aliases": {"n1": [{"text": "oxygen"}]},
             "alias_status": "navigation_metadata_only_not_answer_evidence_or_runtime_fact"}
    layer_path.write_text(json.dumps(layer))
    output = tmp_path / "out.json"
    aliases.apply_layer(graph_path, layer_path, output)
    result = json.loads(output.read_text())
    assert result["nodes"]["n1"]["aliases"] == ["O2", "oxygen"]
    assert result["edges"] == []


def test_protocol_has_no_question_or_gold_inputs():
    assert "question" not in aliases.prepare.__code__.co_varnames
    assert "gold" not in aliases.prepare.__code__.co_varnames
    assert "不得根据未提供的题目" in aliases.EXTRACT
