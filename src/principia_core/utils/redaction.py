from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


SENSITIVE_VALUE = "<REDACTED>"
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|token|password|passwd|private[_-]?key|access[_-]?key|auth)",
    flags=re.IGNORECASE,
)
BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}")
SECRET_TOKEN_RE = re.compile(r"\b(?:sk|pk|rk|ak|xox[baprs]|gh[pousr])-[A-Za-z0-9._~+/=-]{12,}")
JSON_SECRET_KEY_PATTERN = (
    r"(?:[A-Za-z0-9_.-]*(?:api[_-]?key|secret|token|password|passwd|private[_-]?key|access[_-]?key)"
    r"[A-Za-z0-9_.-]*|auth)"
)
JSON_SECRET_RE = re.compile(
    rf"(?i)((?:\"{JSON_SECRET_KEY_PATTERN}\"|'{JSON_SECRET_KEY_PATTERN}'|{JSON_SECRET_KEY_PATTERN})\s*:\s*)"
    r"(\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,}\]]+)",
)
ASSIGNMENT_RE = re.compile(
    r"^([+\- ]?\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_.-]*)(\s*[:=]\s*)(.*?)(\r?\n?)$"
)


def is_sensitive_path(path: str | Path | None) -> bool:
    if path is None:
        return False
    normalized = str(path).replace("\\", "/").strip().strip("'\"")
    if not normalized:
        return False
    if normalized.startswith(("a/", "b/")):
        normalized = normalized[2:]
    name = normalized.rstrip("/").rsplit("/", 1)[-1].lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in {"credentials", "credentials.json", "secrets.json"}
    )


def redact_text(text: object) -> str:
    if text is None:
        return ""

    redacted_lines = []
    for line in str(text).splitlines(keepends=True):
        match = ASSIGNMENT_RE.match(line)
        key = match.group(2) if match else ""
        if key.lower() == "authorization":
            redacted_lines.append(line)
        elif match and SENSITIVE_KEY_RE.search(key):
            redacted_lines.append(
                f"{match.group(1)}{match.group(2)}{match.group(3)}{SENSITIVE_VALUE}{match.group(5)}"
            )
        else:
            redacted_lines.append(line)

    redacted = "".join(redacted_lines)
    redacted = BEARER_RE.sub(rf"\1{SENSITIVE_VALUE}", redacted)
    redacted = JSON_SECRET_RE.sub(_redact_key_value_match, redacted)
    redacted = SECRET_TOKEN_RE.sub(SENSITIVE_VALUE, redacted)
    return redacted


def _redact_key_value_match(match: re.Match) -> str:
    value = match.group(2)
    quote = value[:1] if value[:1] in {"'", '"'} else ""
    if quote:
        return f"{match.group(1)}{quote}{SENSITIVE_VALUE}{quote}"
    return f"{match.group(1)}{SENSITIVE_VALUE}"


def _diff_paths_from_header(line: str) -> Iterable[str]:
    parts = line.strip().split()
    if len(parts) >= 4 and parts[0] == "diff" and parts[1] == "--git":
        yield parts[2]
        yield parts[3]


def filter_sensitive_diff(diff_text: str) -> str:
    output = []
    skipping_sensitive_file = False

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            paths = list(_diff_paths_from_header(line))
            skipping_sensitive_file = any(is_sensitive_path(path) for path in paths)
            if skipping_sensitive_file:
                continue

        if skipping_sensitive_file:
            continue

        output.append(line)

    return redact_text("".join(output))


def redact_file_in_place(path: str | Path) -> None:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return
    original = target.read_text(encoding="utf-8", errors="ignore")
    redacted = redact_text(original)
    if redacted != original:
        target.write_text(redacted, encoding="utf-8")
