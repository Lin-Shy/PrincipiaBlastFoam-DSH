"""通用终态清单校验与传输断路；停用矩阵的续接协议已移除。"""
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop_for_transport(score, *, replayed):
    """Only a new terminal transport problem opens the execution circuit."""
    return not replayed and (score.get('transport_circuit_open') or score.get('reason') in {
        'transport_error', 'http_rejected', 'model_mismatch', 'judge_model_mismatch',
        'local_prompt_token_count_mismatch', 'judge_usage_unknown_or_budget_violation'})


def score_artifact_files(scores):
    return {p.resolve() for pattern in ('**/protocol.json','**/score.json',
            '**/score-binding.json','**/requests/*.json') for p in scores.glob(pattern)}


def validate_inventory_files(scores, inventory):
    expected = inventory['files_sha256']; scores = scores.resolve(); paths = set()
    for name, value in expected.items():
        p = (scores/name).resolve()
        if not p.is_relative_to(scores) or sha(p) != value:
            raise ValueError('Stopped local score/request inventory changed')
        paths.add(p)
    if paths != score_artifact_files(scores):
        raise ValueError('Extra or missing stopped score/request artifacts')
    for p in paths:
        if p.parent.name == 'requests' and read(p).get('status') in {'prepared','in_flight'}:
            raise ValueError('Unresolved prior attempt cannot be continued automatically')
    return True


