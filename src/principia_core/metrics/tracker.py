from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class MetricsTracker:
    """Small in-process tracker used by migrated retrieval code.

    The previous project had a larger singleton metrics subsystem coupled to
    the old workflow harness. Deep Agents/LangSmith can cover tracing later, so
    this class preserves migrated retrieval call sites without pulling in the
    removed harness.
    """

    current_agent: str | None = None
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    _instance: ClassVar["MetricsTracker | None"] = None

    def __new__(cls) -> "MetricsTracker":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.current_agent = None
            cls._instance.llm_calls = []
        return cls._instance

    def record_llm_call(
        self,
        agent_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "unknown",
    ) -> None:
        self.llm_calls.append(
            {
                "agent_name": agent_name,
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "model": model or "unknown",
            }
        )
