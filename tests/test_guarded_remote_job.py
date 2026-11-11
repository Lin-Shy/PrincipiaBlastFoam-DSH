import importlib.util
from pathlib import Path


def guard():
    path = Path(__file__).resolve().parents[1] / 'experiments/end2end/guarded_remote_job.py'
    spec = importlib.util.spec_from_file_location('guard', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_stop_classifies_real_solver_log_lines():
    m = guard()
    assert m.anomaly('max(T): 2463.74438, min(T): 0')['kind'] == 'nonpositive_temperature'
    assert m.anomaly('max(T): 2400, min(T): -1e-6')['kind'] == 'nonpositive_temperature'
    assert m.anomaly('max(p): nan, min(p): 101298')['kind'] == 'nonfinite_or_fatal'
    assert m.anomaly('max(T): 2400, min(T): -nan')['kind'] == 'nonfinite_or_fatal'
    assert m.anomaly('max(T): 4954, min(T): 287.9256438') is None
    assert m.anomaly('Information: finite-volume method') is None


