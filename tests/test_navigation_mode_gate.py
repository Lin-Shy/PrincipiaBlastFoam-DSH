import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))

import navigation_mode_gate as gate


def test_trace_stats_distinguishes_navigation_metadata_from_original_text(tmp_path):
    folder = tmp_path / gate.NAVIGATION_ARM / "sessions" / "q--graph_first--r1"
    folder.mkdir(parents=True)
    result = {
        "id": "q",
        "status": "complete",
        "returned_characters": 500,
        "seen_lines": {"a": {"1": "line"}},
        "events": [
            {
                "action": {"action": "locate"},
                "returned_characters": 200,
                "result": {
                    "status": "ok", "navigation_only": True,
                    "candidates": [{"id": "c"}],
                },
            },
            {
                "action": {"action": "read_sources"},
                "returned_characters": 300,
                "result": {"status": "ok", "items": [{"text": "1: line"}]},
            },
        ],
    }
    (folder / "result.json").write_text(json.dumps(result))

    stats = gate.trace_stats(tmp_path, gate.NAVIGATION_ARM, navigation_expected=True)

    assert stats["read_sources_rate"] == 1
    assert stats["first_locate_mean_characters"] == 200
    assert stats["navigation_original_text_leaks"] == []
    assert stats["invalid_successful_navigation_payloads"] == []
