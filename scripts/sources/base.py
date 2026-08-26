from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceResult:
    """Placeholder result shape for future source integrations."""

    source: str
    implemented: bool = False
    records: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def not_implemented_result(source: str) -> SourceResult:
    return SourceResult(
        source=source,
        implemented=False,
        notes=[f"{source} integration is scaffolded but not implemented yet."],
    )
