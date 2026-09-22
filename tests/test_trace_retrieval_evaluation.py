import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))
import trace_retrieval_evaluation as trace


def test_event_ranges_accepts_items_and_graph_evidence_mapping():
    payload = {
        "items": [{"path": "manual/a.md", "start": 1, "end": 2}],
        "sources": {"s": "tutorials/c/0/U"},
        "evidence": {"e": {"source": "s", "start": 3, "end": 4}},
    }
    rows = list(trace.event_ranges(payload))
    assert rows == [
        {"path": "manual/a.md", "start": 1, "end": 2},
        {"source": "s", "start": 3, "end": 4,
         "path": "tutorials/c/0/U", "evidence_id": "e"},
    ]


def test_extract_units_preserves_event_budget_and_deduplicates_later(tmp_path):
    arm = tmp_path / "arm"
    corpus_root = arm / "skill" / "corpus" / "manual"
    corpus_root.mkdir(parents=True)
    source = corpus_root / "a.md"
    source.write_text("one\ntwo\nthree\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    trace.save(arm / "corpus-manifest.json", {
        "manual/a.md": {"sha256": digest, "lines": 3, "bytes": source.stat().st_size}
    })
    result = {"events": [
        {"step": 0, "returned_characters": 80, "accounting": {"seconds": .1},
         "action": {"action": "search"},
         "result": {"items": [{"path": "manual/a.md", "start": 1, "end": 2}]}},
        {"step": 1, "returned_characters": 20, "accounting": {"seconds": .2},
         "action": {"action": "source"},
         "result": {"items": [{"path": "manual/a.md", "start": 1, "end": 2}]}},
    ]}
    units = trace.extract_units(result, trace.Corpus(arm), {"cases": []})
    assert len(units) == 2
    assert units[0]["cumulative_returned_characters"] == 80
    assert units[1]["cumulative_returned_characters"] == 100
    assert units[1]["cumulative_query_seconds"] == pytest.approx(.3)
    assert len(trace.canonical.deduplicate(units)) == 1
    assert trace.trace_totals(result) == pytest.approx((100, .3, 100))
