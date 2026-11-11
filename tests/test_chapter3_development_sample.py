import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "experiments/end2end" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dedicated_key_never_falls_back_to_inherited_key(tmp_path, monkeypatch):
    runner = load("run_development_sample")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chapter2-do-not-use")
    path = tmp_path / ".env.private"
    path.write_text("CHAPTER3_BASE_URL=https://xcmapi.org/v1\nCHAPTER3_MODEL=test\nCHAPTER3_API_KEY=\n")
    with pytest.raises(ValueError, match="no Chapter 2"):
        runner.configuration(path)


def test_environment_scrubs_old_provider_credentials(tmp_path, monkeypatch):
    runner = load("run_development_sample")
    monkeypatch.setenv("XCM_DEEPSEEK_API_KEY", "old-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "old-key")
    monkeypatch.setenv("QWEN_PROXY_API_KEY", "old-key")
    env = runner.environment({"CHAPTER3_API_KEY": "independent-key"}, tmp_path)
    assert env["PRINCIPIA_CHAPTER3_API_KEY"] == "independent-key"
    assert not any(k in env for k in ["XCM_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", "QWEN_PROXY_API_KEY"])
    assert env["ENABLE_EXECUTION"] == "false"  # Windows MCP never runs the solver.


def test_missing_delivery_is_blocked_and_never_accuracy_scored(tmp_path):
    checker = load("check_development_delivery")
    result = checker.evaluate(tmp_path)
    assert result["status"] == "blocked_before_case_delivery"
    assert result["accuracy_scoring"] == "not_performed"
    assert result["reference_curve_loaded"] is False


def test_empty_case_does_not_imply_model_health(tmp_path):
    checker = load("check_development_delivery")
    (tmp_path / "remote_result/submission/case").mkdir(parents=True)
    result = checker.evaluate(tmp_path)
    assert result["status"] == "development_incomplete"
    assert result["conditions"] == "fail"
    assert result["completion"] == "fail_or_incomplete"
    assert result["model_health"] == "unknown_no_solver_evidence"


def test_declared_quota_cannot_replace_observed_limits_and_guard_stop(tmp_path):
    checker = load("check_development_delivery")
    (tmp_path / "remote_result/submission/case").mkdir(parents=True)
    job = tmp_path / "remote_result/execution_jobs/production_01"
    job.mkdir(parents=True)
    (job / "status.json").write_text(json.dumps({
        "status": "model_anomaly_stop", "memory_limit_bytes": 3*1024**3,
        "command": ["blastFoam", "-case", "/case"], "cpu_affinity": [0],
        "proc_limits": "Max address space         unlimited            unlimited            bytes\n"
    }), encoding="utf-8")
    (job / "process.log").write_text("Time = 1e-8\nmax(T): 2400, min(T): -nan\n", encoding="utf-8")
    result = checker.evaluate(tmp_path)
    assert "guard_memory_limit_missing_or_mismatched" in result["errors"]
    assert result["conditions"] == "fail"
    assert result["completion"] == "fail_or_incomplete"
    assert result["status"] == "model_anomaly_stop"
