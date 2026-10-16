from pathlib import Path
import sys
import threading
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_proxy_model_execution import run_per_model, MODELS


def test_each_model_gets_sixteen_slots_even_with_grouped_input():
    barrier = threading.Barrier(32, timeout=10)
    lock = threading.Lock()
    active = dict.fromkeys(MODELS, 0)
    peaks = dict.fromkeys(MODELS, 0)
    results = []
    def worker(item):
        model, index = item
        with lock:
            active[model] += 1
            peaks[model] = max(peaks[model], active[model])
        barrier.wait()
        with lock:
            active[model] -= 1
        return item
    items = [(m, i) for m in MODELS for i in range(32)]
    run_per_model(items, worker, lambda item, value: results.append(value), model_of=lambda x: x[0])
    assert peaks == dict.fromkeys(MODELS, 16)
    assert not any(active.values()) and sorted(results) == sorted(items)


def test_error_stops_all_new_admissions_and_drains_both_models():
    started, finished, seen = [], [], []
    lock = threading.Lock()
    def worker(item):
        with lock:
            started.append(item)
        if item == (MODELS[0], 0):
            raise RuntimeError('provider circuit')
        with lock:
            finished.append(item)
        return item
    with pytest.raises(RuntimeError, match='provider circuit'):
        run_per_model([(m, i) for m in MODELS for i in range(100)], worker,
            lambda item, value: seen.append(value), model_of=lambda x: x[0])
    assert sorted(started) == sorted((m, i) for m in MODELS for i in range(16))
    assert sorted(finished) == sorted(seen) and len(finished) == 31


@pytest.mark.parametrize('bound', [0, 17, True, 1.0])
def test_invalid_bound_fails_before_worker(bound):
    with pytest.raises(ValueError):
        run_per_model([], None, None, model_of=lambda x: x, workers_per_model=bound)


def test_unknown_model_fails_before_any_worker():
    with pytest.raises(ValueError, match='exact proxy model'):
        run_per_model([MODELS[0], 'replacement-model'], None, None, model_of=lambda x: x)
