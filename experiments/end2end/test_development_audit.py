"""Offline regression checks; no model, SSH, or solver access."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import zstandard

spec = importlib.util.spec_from_file_location("development_audit", Path(__file__).with_name("audit_development_sessions.py"))
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


def test_multiframe_usage_and_nested_duplicates(tmp_path):
    root = tmp_path / "runtime/home/sessions/one"
    root.mkdir(parents=True)
    events = [
        {"type": "assistant/message", "data": {"usage": {"totalTokens": 9, "cacheReadTokens": 3, "inputTokens": 2, "outputTokens": 4}}},
        {"type": "compaction/summary", "data": {"usage": {"totalTokens": 5}}},
        {"type": "tool/call", "data": {"callId": "a", "name": "read"}},
        {"type": "tool/result", "data": {"message": {"content": [{"type": "tool-result", "toolCallId": "a", "isError": True,
            "content": [{"type": "text", "text": "error"}], "structuredContent": {"usage": {"totalTokens": 1000}}}]}}},
        {"type": "request/context", "data": {"usage": {"totalTokens": 2000}}},
    ]
    compressor = zstandard.ZstdCompressor()
    (root / "session.v2.jsonl.zstd").write_bytes(b"".join(compressor.compress((json.dumps(e) + "\n").encode()) for e in events))
    result = audit_module.summarize(tmp_path)
    assert result["reported_usage_including_compaction"]["totalTokens"] == 14
    assert result["sessions"][0]["tool_errors"] == 1
    assert result["sessions"][0]["all_tool_text_characters"] == 5
    assert len(result["sessions"][0]["source_sha256"]) == 64


def test_refuses_overwriting_historical_audit(tmp_path):
    output = tmp_path / "session_audit.json"
    output.write_text("original evidence", encoding="utf-8")
    proc = subprocess.run([sys.executable, "-B", str(Path(audit_module.__file__)), str(tmp_path)], capture_output=True)
    assert proc.returncode != 0
    assert output.read_text(encoding="utf-8") == "original evidence"


def test_corrupt_evidence_is_not_zero_usage(tmp_path):
    import pytest
    source = tmp_path / "bad.zstd"
    source.write_bytes(zstandard.ZstdCompressor().compress(b"not-json\n"))
    with pytest.raises(json.JSONDecodeError):
        audit_module.read_events(source)
