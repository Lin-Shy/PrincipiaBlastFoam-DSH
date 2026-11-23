from __future__ import annotations

import sys
import os
import json
import time
import uuid
from contextlib import redirect_stdout, contextmanager
from pathlib import Path
from typing import Annotated, Any, Dict, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field, BaseModel, ConfigDict

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
NavigationBudget = Annotated[int, Field(ge=1000, le=24000)]
SourceLine = Annotated[int, Field(ge=1)]


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


DEFAULT_REQUIRE_EXECUTION = False


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
    "principia-domain",
    instructions=(
        "Deterministic OpenFOAM case configuration and evidence tools for "
        "PrincipiaBlastFoam. All simulation requires scheduled HPC compute nodes; local execution is blocked."
    ),
)


@contextmanager
def _tool_observation(name: str):
    """Record names and timings on stderr, never query text or credentials."""
    start=time.monotonic();status='ok'
    print(json.dumps({'event':'principia_tool_start','tool':name}),file=sys.stderr,flush=True)
    try:yield
    except Exception:
        status='error';raise
    finally:
        print(json.dumps({'event':'principia_tool_end','tool':name,'status':status,
                          'seconds':round(time.monotonic()-start,6)}),file=sys.stderr,flush=True)




def _call_domain(
    method_name: str,
    *,
    case_path: str,
    user_request: str = "",
    tutorial_path: str | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Call deterministic domain code without corrupting stdio JSON-RPC."""
    with redirect_stdout(sys.stderr), _tool_observation(method_name):
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
def initialize_case(
    case_path: PathText,
    user_request: RequestText,
    tutorial_path: PathText,
    force: bool = False,
) -> Dict[str, Any]:
    """Copy tutorial_path if it is a case (Allrun and Allclean present).

    An explicit case path preserves the locator's selection. A collection path
    instead selects its best deterministic tutorial match. Existing nonempty
    targets are preserved unless force is explicitly requested.
    """
    return _call_domain(
        "initialize_case",
        case_path=case_path,
        user_request=user_request,
        tutorial_path=tutorial_path,
        force=force,
    )


class DictionaryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: PathText
    entry: IdentifierText
    value: Annotated[str, Field(max_length=16000)] | None


@mcp.tool()
def edit_case_dictionaries(
    case_path: PathText,
    edits: Annotated[list[DictionaryEdit], Field(min_length=1, max_length=64)],
    dry_run: bool = False,
) -> str:
    """Apply explicit path/entry/value edits and parse all touched dictionaries before writing.

    Use on an authorized case copy after locating edits. Null removes a literal key.
    Creates missing parents and system/constant dictionaries; preserves regex fallbacks.
    For finite parent groups such as (U|e), effective_lookups reports actual field
    lookup values. Check has_mismatch: a group can parse yet be shadowed by another
    pattern. status describes coverage of listed finite-group checks only;
    not_checked/partial with has_mismatch=null is not a pass. Literal-key precedence,
    arbitrary regexes and runtime validity are not validated by this feedback.
    dry_run validates without writing. No physics inference or solver execution.
    """
    from principia_core.dictionary_edits import apply_dictionary_edits
    case = _validated_case_path(case_path)
    with _tool_observation("edit_case_dictionaries"):
        result = apply_dictionary_edits(case, [edit.model_dump() for edit in edits], dry_run=dry_run)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


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
    _validated_case_path(case_path)
    raise ValueError("Simulation must be submitted through yhbatch on allocated HPC compute nodes")


@mcp.tool()
def complete_workflow(
    case_path: PathText,
    user_request: RequestText,
    tutorial_path: PathText | None = None,
    require_execution: bool = DEFAULT_REQUIRE_EXECUTION,
    require_review: bool = False,
    timeout_seconds: TimeoutSeconds = 3600,
) -> Dict[str, Any]:
    """Finalize and validate evidence; simulation must use the external scheduler."""
    if require_execution:
        raise ValueError("Simulation must be submitted through yhbatch on allocated HPC compute nodes")
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


_untraced_call_tool = mcp.call_tool


async def _traced_call_tool(name: str, arguments: dict[str, Any]):
    """Optional experiment trace; disabled unless the caller configures a directory."""
    directory=os.getenv('PRINCIPIA_TOOL_TRACE_DIR','')
    if not directory:return await _untraced_call_tool(name,arguments)
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    path=root/(str(uuid.uuid4())+'.json');start=time.monotonic()
    record={'tool':name,'arguments':arguments,'started_at':time.time(),'status':'running'}
    def write():
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=lambda x:x.model_dump(mode='json') if hasattr(x,'model_dump') else str(x)))
        temp.replace(path)
    write()
    try:
        result=await _untraced_call_tool(name,arguments)
        record.update(status='ok',result=result)
        return result
    except BaseException as error:
        record.update(status='error',error_type=type(error).__name__)
        raise
    finally:
        record['seconds']=time.monotonic()-start;write()


mcp.call_tool = _traced_call_tool
mcp._mcp_server.call_tool(validate_input=False)(_traced_call_tool)


@mcp.tool()
def get_status() -> Dict[str, Any]:
    return {"service": "principia-domain", "chapter": 3, "execution": "scheduler-only", "knowledge_qa_loaded": False}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
