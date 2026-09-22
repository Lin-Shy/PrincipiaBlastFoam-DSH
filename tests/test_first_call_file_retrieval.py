import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))
import first_call_file_retrieval as first


def test_ranked_files_maps_all_native_shapes_and_deduplicates():
    event = {"result": {
        "items": [
            {"path": "manual/a.md", "start": 1, "end": 2},
            {"path": "manual/a.md", "start": 5, "end": 6},
        ],
        "sources": {"s1": "tutorials/c/0/U"},
        "evidence": {"e1": {"source": "s1", "start": 3, "end": 4}},
        "graph_navigation": (
            "NODE A [src=manual/a.md loc=A community=C]\n"
            "NODE B [src=manual/b.md loc=B community=C]\n"
            "NODE C [src=None loc=None community=C]\n"
        ),
    }}
    assert first.ranked_files(event) == [
        "manual/a.md", "tutorials/c/0/U", "manual/b.md",
    ]


def test_first_retrieval_event_skips_non_retrieval_actions():
    result = {"events": [
        {"action": {"action": "catalog"}, "result": {"items": []}},
        {"action": {"action": "locate"}, "result": {"status": "ok"}},
        {"action": {"action": "search"}, "result": {"items": []}},
    ]}
    assert first.first_retrieval_event(result) == result["events"][1]
