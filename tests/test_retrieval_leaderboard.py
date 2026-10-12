"""统一原文工具的证据可见性与硬预算，独立于评分gold。"""
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))
import retrieval_leaderboard as lb
import leaderboard_results as results


def session():
    engine = SimpleNamespace(files={"a": ["alpha", "beta", "gamma"]},
                             manifest={"a": {"sha256": "fixture"}}, variant="control")
    return lb.Session(engine, "no_graph", "alpha")


def test_numbered_source_preserves_original_seen_lines():
    s = session()
    item = s.source_item("a", 2, 3)
    assert item["text"] == "2: beta\n3: gamma"
    s.observe({"items": [item]})
    assert s.seen == {"a": {"2": "beta", "3": "gamma"}}
    item["text"] = "2: wrong\n3: gamma"
    with pytest.raises(ValueError, match="differs"):
        s.observe({"items": [item]})


def test_search_budget_counts_numbering_and_evidence_identity():
    s = session()
    result, _ = s.dispatch({"action": "search", "query": "alpha"}, 400)
    assert len(lb.qa.wire(result)) <= 400
    assert s.seen["a"]["1"] == "alpha"
    tiny, _ = session().dispatch({"action": "search", "query": "alpha"}, 100)
    assert not tiny["items"]


def test_evidence_group_visibility_is_verified_against_source():
    s = session()
    s.observe({"sources": {"s1": "a"}, "evidence": {
        "e1": {"source": "s1", "start": 1, "end": 2, "text": "1: alpha\n2: beta\n"}}})
    assert s.seen == {"a": {"1": "alpha", "2": "beta"}}


def test_adjudication_lineage_expands_newest_first_and_verifies_parent(tmp_path):
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    older.mkdir(); newer.mkdir()
    results.audit.save(older / "protocol.json", {"prior_adjudication": None, "prior_protocol_sha256": None})
    results.audit.save(newer / "protocol.json", {
        "prior_adjudication": str(older),
        "prior_protocol_sha256": results.audit.sha(older / "protocol.json"),
    })

    expanded = results.adjudication_lineages([older, newer])
    assert expanded == [(newer.resolve(), 0), (older.resolve(), 0)]

    protocol = results.audit.read(newer / "protocol.json")
    protocol["prior_protocol_sha256"] = "0" * 64
    results.audit.save(newer / "protocol.json", protocol)
    with pytest.raises(ValueError, match="prior adjudication drift"):
        results.adjudication_lineages([newer])
