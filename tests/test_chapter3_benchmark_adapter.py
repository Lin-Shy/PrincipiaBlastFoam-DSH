from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ADAPTER_PATH = (
    Path(__file__).resolve().parents[1] / "experiments" / "end2end" / "run_agent_benchmark.py"
)
SPEC = importlib.util.spec_from_file_location("principia_chapter3_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def sample_case() -> dict:
    return {
        "id": "shock_tube_smoke",
        "title": "Shock tube smoke",
        "difficulty": "smoke",
        "tags": ["shock_tube"],
        "user_request": "Create a short shock-tube validation case.",
        "expected": {
            "max_end_time": 0.0005,
            "required_reports": ["physics_report.md", "execution_status.json"],
            "preferred_case_keywords": ["shockTube"],
        },
    }


def test_builds_headless_dsh_command_without_secret_or_execution() -> None:
    case_path = Path("/tmp/results/cases/shock_tube_smoke")
    prompt = adapter.build_case_prompt(
        sample_case(),
        case_path,
        Path("/tmp/tutorials"),
        execution_enabled=False,
    )
    command = adapter.build_dsh_command(
        Path("/opt/dsh/bin.js"),
        "headless",
        prompt,
        [Path("/tmp/principia-patch.js")],
    )

    assert command[:5] == [
        "/opt/dsh/bin.js",
        "--profile",
        "headless",
        "--patch",
        "/tmp/principia-patch.js",
    ]
    assert command[-1] == prompt
    assert "Execution is disabled" in prompt
    assert "Do not invoke blastFoam" in prompt
    assert f"{adapter.COMPLETION_MARKER} case_id=shock_tube_smoke" in prompt
    assert adapter.public_command(command)[-1] == "<benchmark-prompt>"
    assert "DEEPSEEK_API_KEY" not in json.dumps(adapter.public_command(command))


def test_dry_run_writes_chapter3_compatible_contract_without_case(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"name": "adapter-test", "version": "1", "cases": [sample_case()]}),
        encoding="utf-8",
    )
    output_root = tmp_path / "raw_runs"

    exit_code = adapter.main(
        [
            "--cases-file",
            str(cases_path),
            "--output-root",
            str(output_root),
            "--dsh-bin",
            "/does/not/need/to/exist/in/dry-run",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    reports = list(output_root.glob("run_*/benchmark_report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["benchmark"]["name"] == "adapter-test"
    assert report["settings"]["adapter"] == "principia-blastfoam-dsh"
    assert report["settings"]["execution_enabled"] is False
    assert report["aggregate"]["cases_total"] == 1
    assert report["aggregate"]["cases_executed"] == 0

    result = report["results"][0]
    assert set(result) == {
        "case_id",
        "title",
        "tags",
        "difficulty",
        "run",
        "summary",
        "benchmark_passed",
        "cleanup",
    }
    assert result["run"]["dry_run"] is True
    assert result["run"]["exit_code"] is None
    assert result["benchmark_passed"] is False
    assert result["run"]["command"][-1] == "<benchmark-prompt>"
    assert not Path(result["summary"]["case_path"]).exists()
    assert not (reports[0].parent / "logs").exists()


def test_case_selection_rejects_unknown_id() -> None:
    try:
        adapter.select_cases([sample_case()], ["not-a-case"], None)
    except ValueError as error:
        assert "unknown case id" in str(error)
    else:
        raise AssertionError("unknown case id should be rejected")
