from __future__ import annotations

import os
import re
from typing import Dict, List


AGENT_ERROR_RE = re.compile(
    r"(error executing agent|connection error|api connection error|agent timeout|no output generated)",
    flags=re.IGNORECASE,
)
PLACEHOLDER_RESPONSE_RE = re.compile(
    r"^\s*(?:sorry[,\s]*)?(?:i\s+)?(?:need|require|would need)\s+"
    r"(?:more|additional)\s+(?:steps|time|information|context)\b"
    r"|^\s*(?:sorry[,\s]*)?(?:i\s+)?(?:cannot|can't|can not)\s+"
    r"(?:complete|process|finish)\s+this\s+request\b"
    r"|^\s*(?:please\s+)?(?:continue|provide more context)\b",
    flags=re.IGNORECASE,
)
RAW_TOOL_OUTPUT_RE = re.compile(
    r"^\s*(?:---\s*)?Retrieved Documentation Information(?:\s*---)?"
    r"|^\s*Observation:\s*"
    r"|^\s*Tool output:\s*",
    flags=re.IGNORECASE,
)


def _single_line(text: str, limit: int = 220) -> str:
    return " ".join((text or "").strip().split())[:limit]


REPORT_DEFAULT_MAX_CHARS = {
    "physics_report": 6000,
    "execution_report": 3200,
    "review_report": 2400,
    "post_processing_report": 3200,
}


def report_max_chars(report_name: str) -> int:
    normalized = report_name.replace(".md", "").strip()
    env_key = f"{normalized.upper()}_MAX_CHARS"
    default = REPORT_DEFAULT_MAX_CHARS.get(normalized, 4000)
    try:
        return max(1000, int(os.getenv(env_key, os.getenv("AGENT_REPORT_MAX_CHARS", str(default)))))
    except ValueError:
        return default


def report_length_instruction(report_name: str) -> str:
    max_chars = report_max_chars(report_name)
    return (
        f"Keep the final {report_name} concise and evidence-focused, under about {max_chars} characters. "
        "Use short checklist bullets and cite artifact filenames instead of copying long logs or full files."
    )


def compact_agent_report(text: str, report_name: str) -> str:
    """Bound report size while preserving the beginning and final conclusion."""
    content = (text or "").strip()
    max_chars = report_max_chars(report_name)
    if len(content) <= max_chars:
        return content

    marker = (
        "\n\n[Report compacted: middle detail omitted to enforce the workflow report length budget. "
        "Use workflow_evidence.md, execution_status.json, and artifact_contract.json for full deterministic evidence.]\n\n"
    )
    tail_chars = min(900, max_chars // 4)
    head_chars = max_chars - len(marker) - tail_chars
    if head_chars < 500:
        return content[:max_chars]
    return content[:head_chars].rstrip() + marker + content[-tail_chars:].lstrip()


def report_error_reasons(text: str) -> List[str]:
    content = text or ""
    stripped = content.strip()
    reasons: List[str] = []
    if not stripped:
        reasons.append("report is empty")
    if AGENT_ERROR_RE.search(content):
        reasons.append("report contains an agent/tool connection error")
    if PLACEHOLDER_RESPONSE_RE.search(stripped):
        reasons.append("report is a placeholder continuation response")
    if RAW_TOOL_OUTPUT_RE.search(stripped):
        reasons.append("report appears to be raw tool/retrieval output instead of an analysis report")
    return reasons


def validate_agent_report(text: str, report_name: str, min_chars: int = 80) -> Dict[str, object]:
    reasons = report_error_reasons(text)
    if len((text or "").strip()) < min_chars:
        reasons.append(f"{report_name} is shorter than the minimum content contract")
    return {
        "valid": not reasons,
        "reason": "; ".join(reasons),
        "reasons": reasons,
        "excerpt": _single_line(text),
    }


def build_report_repair_prompt(
    *,
    report_name: str,
    original_task: str,
    invalid_report: str,
    validation: Dict[str, object],
) -> str:
    reasons = validation.get("reasons") or []
    reason_text = "\n".join(f"- {reason}" for reason in reasons) or "- report failed validation"
    excerpt = _single_line(invalid_report, limit=600)
    return (
        f"The previous {report_name} did not satisfy the workflow report contract.\n"
        f"Validation issues:\n{reason_text}\n\n"
        f"Previous output excerpt:\n{excerpt}\n\n"
        f"Original task:\n{original_task}\n\n"
        "Produce a complete, self-contained Markdown report now. "
        "Do not ask for more steps, do not output raw tool results, and do not use placeholder text. "
        f"{report_length_instruction(report_name)} "
        "If execution or validation failed, still write a concrete failure report with the command/log evidence "
        "available in the case directory."
    )
