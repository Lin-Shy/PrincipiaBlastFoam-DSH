import json
from pathlib import Path
import sys
import threading

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'
sys.path.insert(0, str(SOURCE))
import chapter2_local_score_continuation as continuation
from chapter2_local_bounded_execution import run_bounded


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


@pytest.mark.parametrize('reason', ['transport_error', 'http_rejected', 'model_mismatch',
    'judge_model_mismatch', 'local_prompt_token_count_mismatch',
    'judge_usage_unknown_or_budget_violation'])
def test_only_new_transport_failures_open_circuit(reason):
    score = {'status': 'judge_unknown', 'reason': reason}
    assert continuation.stop_for_transport(score, replayed=False)
    assert not continuation.stop_for_transport(score, replayed=True)


def test_cached_unknown_is_observed_once_and_remaining_work_continues():
    calls = []; observed = []
    def worker(item):
        if item == 0:
            return {'reason': 'transport_error'}, True
        calls.append(item)
        return {'status': 'judged'}, False
    def observe(item, result):
        observed.append(item)
        score, replayed = result
        if continuation.stop_for_transport(score, replayed=replayed):
            raise RuntimeError('circuit')
    run_bounded(range(20), worker, observe, 8)
    assert sorted(calls) == list(range(1, 20))
    assert sorted(observed) == list(range(20))


def test_new_failure_stops_dispatch_and_drains_without_retry():
    admitted = []; observed = []; barrier = threading.Barrier(8)
    def worker(item):
        admitted.append(item)
        barrier.wait(timeout=5)
        return {'reason': 'transport_error'}
    def observe(item, score):
        observed.append(item)
        if continuation.stop_for_transport(score, replayed=False):
            raise RuntimeError('circuit')
    with pytest.raises(RuntimeError, match='circuit'):
        run_bounded(range(30), worker, observe, 8)
    assert sorted(admitted) == sorted(observed) == list(range(8))


def inventory_fixture(tmp_path):
    scores = tmp_path / 'scores'
    request = write(scores / 'main/model/r01/sessions/Q01/requests/00.json',
                    {'status': 'transport_error', 'transport_attempts': 1})
    score = write(request.parent.parent / 'score.json', {'status': 'judge_unknown'})
    return scores, request, {'files_sha256': {
        p.relative_to(scores).as_posix(): continuation.sha(p) for p in (request, score)}}


def test_inventory_accepts_terminal_failure_without_mutation(tmp_path):
    scores, request, inventory = inventory_fixture(tmp_path)
    before = request.read_bytes()
    assert continuation.validate_inventory_files(scores, inventory)
    assert request.read_bytes() == before


@pytest.mark.parametrize('mutation', ['changed', 'missing', 'extra', 'escape', 'in_flight'])
def test_inventory_rejects_unsafe_continuation(tmp_path, mutation):
    scores, request, inventory = inventory_fixture(tmp_path)
    if mutation == 'changed':
        write(request, {'status': 'response'})
    elif mutation == 'missing':
        request.unlink()
    elif mutation == 'extra':
        write(request.with_name('01.json'), {'status': 'response'})
    elif mutation == 'escape':
        outside = write(tmp_path / 'outside.json', {})
        inventory['files_sha256']['../outside.json'] = continuation.sha(outside)
    else:
        write(request, {'status': 'in_flight'})
        inventory['files_sha256'][request.relative_to(scores).as_posix()] = continuation.sha(request)
    with pytest.raises((ValueError, FileNotFoundError)):
        continuation.validate_inventory_files(scores, inventory)


