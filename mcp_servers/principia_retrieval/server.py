from __future__ import annotations

import sys
import os
from contextlib import redirect_stdout
from pathlib import Path
from typing import Annotated, Any, Dict, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_servers.principia_retrieval.retrieval_service import get_service
from principia_core.openfoam import OpenFOAMDomainService


PROJECT_ROOT = Path(__file__).resolve().parents[2]

PathText = Annotated[str, Field(min_length=1, max_length=4096)]
RequestText = Annotated[str, Field(min_length=1, max_length=32768)]
QueryText = Annotated[str, Field(max_length=32768)]
IdentifierText = Annotated[str, Field(min_length=1, max_length=512)]
ResultIdText = Annotated[str, Field(min_length=1, max_length=128)]
TopK = Annotated[int, Field(ge=1, le=20)]
LineLimit = Annotated[int, Field(ge=1, le=1000)]
IterationLimit = Annotated[int, Field(ge=1, le=10)]
TimeoutSeconds = Annotated[int, Field(ge=1, le=86400)]
DetailLevel = Literal["candidates", "detail", "content", "full", "legacy", "all"]


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


DEFAULT_REQUIRE_EXECUTION = _bool_env("REQUIRE_EXECUTION", True)


def _configured_root(env_name: str, default: Path | None = None) -> Path:
    raw = os.getenv(env_name, "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        return candidate.resolve()
    if default is not None:
        return default.resolve()
    raise ValueError(f"{env_name} must be configured before this MCP operation")


def _validated_path(value: str, *, root: Path, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError(f"{label} must stay within configured root {root}: {candidate}")
    return candidate


def _validated_case_path(case_path: str) -> Path:
    root = _configured_root("PRINCIPIA_CASE_ROOT", PROJECT_ROOT / "outputs")
    candidate = _validated_path(case_path, root=root, label="case_path")
    if candidate == root:
        raise ValueError("case_path must name a case below PRINCIPIA_CASE_ROOT, not the root itself")
    return candidate


def _validated_tutorial_path(tutorial_path: str) -> Path:
    root = _configured_root("BLASTFOAM_TUTORIALS")
    return _validated_path(tutorial_path, root=root, label="tutorial_path")


mcp = FastMCP(
    "principia-blastfoam",
    instructions=(
        "Knowledge retrieval and deterministic OpenFOAM workflow tools for "
        "PrincipiaBlastFoam. Solver execution is enabled by default and can be "
        "disabled explicitly with ENABLE_EXECUTION=false."
    ),
)


def _call_service(method_name: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    # stdio MCP uses stdout for JSON-RPC. Keep legacy retriever print output on stderr.
    with redirect_stdout(sys.stderr):
        method = getattr(get_service(), method_name)
        return method(*args, **kwargs)


def _call_domain(
    method_name: str,
    *,
    case_path: str,
    user_request: str = "",
    tutorial_path: str | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Call deterministic domain code without corrupting stdio JSON-RPC."""
    with redirect_stdout(sys.stderr):
        validated_case = _validated_case_path(case_path)
        validated_tutorial = (
            _validated_tutorial_path(tutorial_path)
            if tutorial_path is not None
            else Path(os.getenv("BLASTFOAM_TUTORIALS") or PROJECT_ROOT)
        )
        service = OpenFOAMDomainService(
            case_path=validated_case,
            user_request=user_request,
            tutorial_path=validated_tutorial,
        )
        method = getattr(service, method_name)
        return method(**kwargs)


@mcp.tool()
def get_status() -> Dict[str, Any]:
    """Return server status and loaded knowledge graph statistics."""
    return _call_service("get_status")


@mcp.tool()
def get_case_by_intent(query: RequestText) -> Dict[str, Any]:
    """Resolve a user query or alias such as DDT to a known blastFoam tutorial case."""
    return _call_service("get_case_by_intent", query)


@mcp.tool()
def get_files_for_case(case_path: PathText) -> Dict[str, Any]:
    """Return files known for a tutorial case path."""
    return _call_service("get_files_for_case", case_path)


@mcp.tool()
def find_variable(case_path: PathText, variable_name: IdentifierText) -> Dict[str, Any]:
    """Find files in a case that define a variable by exact variable name."""
    return _call_service("find_variable", case_path, variable_name)


@mcp.tool()
def get_file_content(
    case_path: PathText,
    file_path: PathText,
    max_lines: LineLimit = 120,
) -> Dict[str, Any]:
    """Read tutorial file content from BLASTFOAM_TUTORIALS."""
    return _call_service("get_file_content", case_path, file_path, max_lines=max_lines)


@mcp.tool()
def get_modification_targets(
    user_request: RequestText,
    case_path: PathText | None = None,
    top_k: TopK = 5,
) -> Dict[str, Any]:
    """Return likely case files that should be modified for a user request."""
    return _call_service("get_modification_targets", user_request, case_path=case_path, top_k=top_k)


@mcp.tool()
def search_case_content(
    query: QueryText = "",
    case_path: PathText | None = None,
    file_path: PathText | None = None,
    variable_name: IdentifierText | None = None,
    top_k: TopK = 5,
    include_file_content: bool = False,
    max_iterations: IterationLimit = 1,
    detail_level: DetailLevel = "candidates",
    result_id: ResultIdText | None = None,
    max_detail_lines: LineLimit = 120,
) -> Dict[str, Any]:
    """Search case content in two stages. Defaults to candidates; use detail_level='detail' with result_id for content."""
    return _call_service(
        "search_case_content",
        query,
        case_path=case_path,
        file_path=file_path,
        variable_name=variable_name,
        top_k=top_k,
        include_file_content=include_file_content,
        max_iterations=max_iterations,
        detail_level=detail_level,
        result_id=result_id,
        max_detail_lines=max_detail_lines,
    )


@mcp.tool()
def search_user_guide(
    query: QueryText = "",
    top_k: TopK = 5,
    detail_level: DetailLevel = "candidates",
    result_id: ResultIdText | None = None,
) -> Dict[str, Any]:
    """Search the BlastFoam user guide in two stages. Defaults to candidates; use detail_level='detail' with result_id for content."""
    return _call_service(
        "search_user_guide",
        query,
        top_k=top_k,
        detail_level=detail_level,
        result_id=result_id,
    )


@mcp.tool()
def initialize_case(
    case_path: PathText,
    user_request: RequestText,
    tutorial_path: PathText,
    force: bool = False,
) -> Dict[str, Any]:
    """Initialize case_path from the best deterministic tutorial match."""
    return _call_domain(
        "initialize_case",
        case_path=case_path,
        user_request=user_request,
        tutorial_path=tutorial_path,
        force=force,
    )


@mcp.tool()
def case_digest(case_path: PathText, user_request: QueryText = "") -> Dict[str, Any]:
    """Return a bounded digest of OpenFOAM dictionaries in case_path."""
    return _call_domain("case_digest", case_path=case_path, user_request=user_request)


@mcp.tool()
def execution_preflight(case_path: PathText) -> Dict[str, Any]:
    """Check execution environment, case scripts, privileges, and commands."""
    return _call_domain("execution_preflight", case_path=case_path)


@mcp.tool()
def run_case(
    case_path: PathText,
    user_request: RequestText,
    timeout_seconds: TimeoutSeconds = 3600,
) -> Dict[str, Any]:
    """Run case_path once unless ENABLE_EXECUTION is explicitly false."""
    return _call_domain(
        "run_case",
        case_path=case_path,
        user_request=user_request,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def complete_workflow(
    case_path: PathText,
    user_request: RequestText,
    tutorial_path: PathText | None = None,
    require_execution: bool = DEFAULT_REQUIRE_EXECUTION,
    require_review: bool = False,
    timeout_seconds: TimeoutSeconds = 3600,
) -> Dict[str, Any]:
    """Finalize, execute by default, and validate required workflow artifacts."""
    with redirect_stdout(sys.stderr):
        validated_case = _validated_case_path(case_path)
        validated_tutorial = (
            _validated_tutorial_path(tutorial_path)
            if tutorial_path is not None
            else Path(os.getenv("BLASTFOAM_TUTORIALS") or PROJECT_ROOT)
        )
        service = OpenFOAMDomainService(
            case_path=validated_case,
            user_request=user_request,
            tutorial_path=validated_tutorial,
            require_execution=require_execution,
            require_review=require_review,
        )
        return service.complete(timeout_seconds=timeout_seconds)


@mcp.tool()
def write_evidence(case_path: PathText) -> Dict[str, Any]:
    """Write deterministic workflow_evidence.md and its JSON companion."""
    return _call_domain("write_evidence", case_path=case_path)


@mcp.tool()
def write_post_processing(case_path: PathText) -> Dict[str, Any]:
    """Write post_processing_report.md from available time/probe outputs."""
    return _call_domain("write_post_processing_report", case_path=case_path)


@mcp.tool()
def validate_artifacts(
    case_path: PathText,
    require_execution: bool = DEFAULT_REQUIRE_EXECUTION,
    require_review: bool = False,
) -> Dict[str, Any]:
    """Validate workflow artifact contracts and write artifact_contract.json."""
    return _call_domain(
        "validate_artifacts",
        case_path=case_path,
        require_execution=require_execution,
        require_review=require_review,
    )


@mcp.tool()
def diagnostics(case_path: PathText) -> Dict[str, Any]:
    """Classify fatal and nonfatal diagnostics in OpenFOAM logs."""
    return _call_domain("diagnostics", case_path=case_path)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
