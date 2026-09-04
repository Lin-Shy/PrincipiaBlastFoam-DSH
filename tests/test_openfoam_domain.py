from __future__ import annotations

from pathlib import Path
import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from principia_core.openfoam import (
    OpenFOAMDomainService,
    _build_allrun_shell_command,
    initialize_case_from_tutorial,
    make_openfoam_tools,
    run_openfoam_case_once,
)
from principia_core.utils.execution_status import build_execution_status
from principia_core.utils.execution_preflight import (
    DEFAULT_BLASTFOAM_BASHRC,
    DEFAULT_OPENFOAM_BASHRC,
    run_execution_preflight,
)
from principia_core.utils.openfoam_diagnostics import (
    classify_case_openfoam_logs,
    summarize_diagnostics,
)
from principia_core.utils.report_contracts import report_error_reasons
from principia_core.utils.workflow_artifacts import validate_workflow_artifacts
from mcp_servers.principia_retrieval import server as mcp_server


TUTORIAL_ROOT = Path(__file__).resolve().parents[2] / "blastFoam_tutorials"


def test_initializer_selects_axisymmetric_charge(tmp_path: Path) -> None:
    result = initialize_case_from_tutorial(
        case_path=tmp_path,
        user_request="模拟触地地表爆炸，并使最远比例距离接近 3。",
        tutorial_path=TUTORIAL_ROOT,
    )

    assert result["initialized"] is True
    assert result["tutorial_case_path"] == "blastFoam/axisymmetricCharge"
    assert (tmp_path / "Allrun").exists()
    assert (tmp_path / "system" / "controlDict").exists()


def test_initializer_selects_shock_tube_not_triple_point(tmp_path: Path) -> None:
    result = initialize_case_from_tutorial(
        case_path=tmp_path,
        user_request="运行真实 blastFoam 激波管短时 smoke。",
        tutorial_path=TUTORIAL_ROOT,
    )

    assert result["initialized"] is True
    assert result["tutorial_case_path"] == "blastFoam/shockTube_tabulated"


def test_domain_service_completes_nonexecution_artifacts(tmp_path: Path) -> None:
    control = tmp_path / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text(
        "application blastFoam;\nendTime 0.02;\nwriteInterval 0.001;\n",
        encoding="utf-8",
    )
    service = OpenFOAMDomainService(
        case_path=tmp_path,
        user_request="短时 smoke test，endTime 控制在 0.0005 秒以内。",
        tutorial_path=TUTORIAL_ROOT,
        require_execution=False,
    )

    result = service.complete(timeout_seconds=30)

    assert result["terminal_success"] is True
    assert result["artifact_contract_ok"] is True
    assert (tmp_path / "physics_report.md").exists()
    assert (tmp_path / "workflow_evidence.md").exists()
    assert (tmp_path / "post_processing_report.md").exists()
    assert (tmp_path / "artifact_contract.json").exists()
    assert "endTime 0.0005;" in control.read_text(encoding="utf-8")


def test_execution_can_be_disabled_explicitly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_EXECUTION", "false")

    result = run_openfoam_case_once(tmp_path)

    assert result == {
        "started": False,
        "blocked": True,
        "reason": "ENABLE_EXECUTION is explicitly false; solver was not started.",
    }


def test_execution_is_enabled_by_default_but_preflight_still_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("ENABLE_EXECUTION", raising=False)
    monkeypatch.setenv("OPENFOAM_BASHRC", str(tmp_path / "missing-bashrc"))

    result = run_openfoam_case_once(tmp_path)

    assert result["started"] is False
    assert result["blocked"] is True
    assert "preflight" in result
    assert "does not point to a readable file" in " ".join(result["preflight"]["blockers"])


def test_domain_run_case_disabled_reports_skipped_not_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_EXECUTION", "false")
    control = tmp_path / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text(
        "application blastFoam;\nendTime 0.01;\nwriteInterval 0.001;\n",
        encoding="utf-8",
    )
    service = OpenFOAMDomainService(
        case_path=tmp_path,
        user_request="短时 smoke test，endTime 控制在 0.0005 秒以内。",
        tutorial_path=TUTORIAL_ROOT,
    )

    result = service.run_case(timeout_seconds=30)
    physics_report = (tmp_path / "physics_report.md").read_text(encoding="utf-8")
    execution_report = (tmp_path / "execution_report.md").read_text(encoding="utf-8")

    assert result["blocked"] is True
    assert "Controlled solver execution is enabled" not in physics_report
    assert "No solver execution was started" in physics_report
    assert "Solver execution was skipped" in execution_report
    assert not (tmp_path / "execution_status.json").exists()


def test_openfoam_shell_command_sources_configured_environments(tmp_path: Path, monkeypatch) -> None:
    openfoam_bashrc = tmp_path / "OpenFOAM-bashrc"
    blastfoam_bashrc = tmp_path / "blastFoam-bashrc"
    openfoam_bashrc.write_text("# OpenFOAM\n", encoding="utf-8")
    blastfoam_bashrc.write_text("# blastFoam\n", encoding="utf-8")
    monkeypatch.setenv("OPENFOAM_BASHRC", str(openfoam_bashrc))
    monkeypatch.setenv("BLASTFOAM_BASHRC", str(blastfoam_bashrc))

    command = _build_allrun_shell_command(tmp_path)

    assert f"source {openfoam_bashrc}" in command
    assert f"MAKE=True source {blastfoam_bashrc}" in command
    assert command.endswith("./Allrun")


def test_preflight_portable_defaults_rely_on_current_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.delenv("OPENFOAM_BASHRC", raising=False)
    monkeypatch.delenv("BLASTFOAM_BASHRC", raising=False)
    monkeypatch.delenv("OPENFOAM_EXECUTION_USER", raising=False)

    result = run_execution_preflight(tmp_path)
    warnings = " ".join(result["warnings"])

    assert result["ok"] is True
    assert DEFAULT_OPENFOAM_BASHRC == ""
    assert DEFAULT_BLASTFOAM_BASHRC == ""
    assert "OPENFOAM_BASHRC is not configured" in warnings
    assert "BLASTFOAM_BASHRC is not configured" in warnings


def test_preflight_blocks_explicit_missing_environment_script(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "Allrun").write_text("#!/bin/sh\n", encoding="utf-8")
    missing_bashrc = tmp_path / "missing-openfoam-bashrc"
    monkeypatch.setenv("OPENFOAM_BASHRC", str(missing_bashrc))
    monkeypatch.delenv("BLASTFOAM_BASHRC", raising=False)
    monkeypatch.delenv("OPENFOAM_EXECUTION_USER", raising=False)

    result = run_execution_preflight(tmp_path)

    assert result["ok"] is False
    assert any(
        "OPENFOAM_BASHRC does not point to a readable file" in blocker
        for blocker in result["blockers"]
    )


def test_nested_solver_log_evidence_and_diagnostics(tmp_path: Path) -> None:
    clean_log = tmp_path / "sector" / "log.blastFoam"
    clean_log.parent.mkdir(parents=True)
    clean_log.write_text("Time = 0.0001\n\nEnd\n", encoding="utf-8")
    failed_log = tmp_path / "building3D" / "log.blastFoam"
    failed_log.parent.mkdir(parents=True)
    failed_log.write_text("Time = 0.1\nFOAM FATAL ERROR\nbad boundary\n", encoding="utf-8")

    status = build_execution_status(tmp_path, "completed", "completed")
    diagnostics = classify_case_openfoam_logs(tmp_path)
    summary = summarize_diagnostics(diagnostics)

    assert status["final_status"] == "failed"
    assert summary["blocking"] == 1


def test_execution_contract_rejects_blocking_logs(tmp_path: Path) -> None:
    (tmp_path / "physics_report.md").write_text(
        "# Physics Report\n\n" + "valid physical configuration evidence " * 12,
        encoding="utf-8",
    )
    (tmp_path / "execution_report.md").write_text(
        "# Execution Report\n\n" + "solver execution evidence and status " * 12,
        encoding="utf-8",
    )
    (tmp_path / "post_processing_report.md").write_text(
        "# Post-Processing Report\n\n" + "post-processing output evidence " * 12,
        encoding="utf-8",
    )
    log = tmp_path / "log.blastFoam"
    log.write_text("FOAM FATAL ERROR\nbad boundary\n", encoding="utf-8")

    contract = validate_workflow_artifacts(
        tmp_path,
        state={"execution_status": {"run_status": "completed", "final_status": "success"}},
        require_execution=True,
    )

    assert contract["ok"] is False
    assert "OpenFOAM blocking diagnostics present" in " ".join(contract["issues"])


def test_framework_adapter_is_plain_python(tmp_path: Path) -> None:
    tools = make_openfoam_tools(
        case_path=tmp_path,
        user_request="inspect this case",
        tutorial_path=TUTORIAL_ROOT,
    )

    assert {function.__name__ for function in tools} == {
        "initialize_case",
        "case_digest",
        "execution_preflight",
        "run_openfoam_case",
        "complete_workflow",
        "write_evidence",
        "write_post_processing_report",
        "validate_artifacts",
        "openfoam_diagnostics",
    }
    assert all(callable(function) for function in tools)


def test_framework_run_adapter_respects_disabled_execution_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_EXECUTION", "false")
    control = tmp_path / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text(
        "application blastFoam;\nendTime 0.01;\nwriteInterval 0.001;\n",
        encoding="utf-8",
    )
    tools = make_openfoam_tools(
        case_path=tmp_path,
        user_request="短时 smoke test，endTime 控制在 0.0005 秒以内。",
        tutorial_path=TUTORIAL_ROOT,
    )
    run_adapter = next(function for function in tools if function.__name__ == "run_openfoam_case")

    result = run_adapter(timeout_seconds=30)
    physics_report = (tmp_path / "physics_report.md").read_text(encoding="utf-8")

    assert '"blocked": true' in result
    assert "Controlled solver execution is enabled" not in physics_report


def test_report_contract_rejects_agent_transport_errors() -> None:
    report = "# Execution Report\n\nAPI connection error while calling model."

    assert "report contains an agent/tool connection error" in report_error_reasons(report)


def test_mcp_exposes_domain_tools_and_completes_without_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    listed_tools = asyncio.run(mcp_server.mcp.list_tools())
    tool_names = {tool.name for tool in listed_tools}
    assert {
        "initialize_case",
        "case_digest",
        "execution_preflight",
        "run_case",
        "complete_workflow",
        "write_evidence",
        "write_post_processing",
        "validate_artifacts",
        "diagnostics",
    } <= tool_names
    complete_tool = next(tool for tool in listed_tools if tool.name == "complete_workflow")
    assert complete_tool.inputSchema["properties"]["require_execution"]["default"] is True

    monkeypatch.setenv("PRINCIPIA_CASE_ROOT", str(tmp_path))
    case_path = tmp_path / "safe-case"
    control = case_path / "system" / "controlDict"
    control.parent.mkdir(parents=True)
    control.write_text(
        "application blastFoam;\nendTime 0.01;\nwriteInterval 0.001;\n",
        encoding="utf-8",
    )
    result = mcp_server.complete_workflow(
        case_path=str(case_path),
        user_request="短时 smoke test，endTime 控制在 0.0005 秒以内。",
        require_execution=False,
        require_review=False,
    )

    assert result["terminal_success"] is True
    assert result["artifact_contract_ok"] is True


def test_mcp_domain_tools_reject_case_path_escape(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    monkeypatch.setenv("PRINCIPIA_CASE_ROOT", str(allowed))

    try:
        mcp_server.write_evidence(str(outside))
    except ValueError as exc:
        assert "must stay within configured root" in str(exc)
    else:
        raise AssertionError("case path outside PRINCIPIA_CASE_ROOT was accepted")

    try:
        mcp_server.write_evidence(str(allowed))
    except ValueError as exc:
        assert "must name a case below" in str(exc)
    else:
        raise AssertionError("PRINCIPIA_CASE_ROOT itself was accepted as a case")


def test_mcp_domain_tools_reject_tutorial_path_escape(tmp_path: Path, monkeypatch) -> None:
    case_root = tmp_path / "cases"
    tutorial_root = tmp_path / "tutorials"
    monkeypatch.setenv("PRINCIPIA_CASE_ROOT", str(case_root))
    monkeypatch.setenv("BLASTFOAM_TUTORIALS", str(tutorial_root))

    try:
        mcp_server.initialize_case(
            case_path="safe-case",
            user_request="shock tube",
            tutorial_path=str(tmp_path / "outside-tutorials"),
        )
    except ValueError as exc:
        assert "tutorial_path must stay within configured root" in str(exc)
    else:
        raise AssertionError("tutorial path outside BLASTFOAM_TUTORIALS was accepted")


@pytest.mark.parametrize(
    ("tool_name", "extra_arguments"),
    [
        ("initialize_case", {"user_request": "shock tube", "tutorial_path": "."}),
        ("case_digest", {}),
        ("execution_preflight", {}),
        ("run_case", {"user_request": "do not execute"}),
        ("complete_workflow", {"user_request": "non-execution", "require_execution": False}),
        ("write_evidence", {}),
        ("write_post_processing", {}),
        ("validate_artifacts", {}),
        ("diagnostics", {}),
    ],
)
def test_every_domain_tool_rejects_case_path_escape(
    tool_name: str,
    extra_arguments: dict[str, object],
    tmp_path: Path,
    monkeypatch,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    tutorial_root = tmp_path / "tutorials"
    monkeypatch.setenv("PRINCIPIA_CASE_ROOT", str(allowed))
    monkeypatch.setenv("BLASTFOAM_TUTORIALS", str(tutorial_root))

    with pytest.raises(ValueError, match="must stay within configured root"):
        getattr(mcp_server, tool_name)(case_path=str(outside), **extra_arguments)


def test_mcp_case_path_rejects_symlink_escape(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "linked-case").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("PRINCIPIA_CASE_ROOT", str(allowed))

    with pytest.raises(ValueError, match="must stay within configured root"):
        mcp_server.write_evidence("linked-case")


def test_mcp_schemas_bound_expensive_arguments() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}

    assert len(tools) == 17
    assert tools["search_case_content"].inputSchema["properties"]["top_k"]["maximum"] == 20
    assert tools["search_case_content"].inputSchema["properties"]["max_iterations"]["maximum"] == 10
    assert tools["get_file_content"].inputSchema["properties"]["max_lines"]["maximum"] == 1000
    assert tools["run_case"].inputSchema["properties"]["timeout_seconds"]["maximum"] == 86400


def test_mcp_validation_rejects_out_of_range_arguments() -> None:
    async def exercise() -> None:
        with pytest.raises(ToolError, match="less than or equal to 1000"):
            await mcp_server.mcp.call_tool(
                "get_file_content",
                {
                    "case_path": "blastFoam/freeField",
                    "file_path": "system/controlDict",
                    "max_lines": 1001,
                },
            )
        with pytest.raises(ToolError, match="greater than or equal to 1"):
            await mcp_server.mcp.call_tool("search_user_guide", {"top_k": 0})

    asyncio.run(exercise())
