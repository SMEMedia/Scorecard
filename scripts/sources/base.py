from __future__ import annotations

from dataclasses import dataclass, field
import json
from collections.abc import Callable
from pathlib import Path
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


def configured_scorecard_metrics(config_path: str | Path) -> list[str]:
    """Return user-facing scorecard columns declared by an enabled source config."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    metrics: set[str] = set()
    mapping_keys = {
        "columns",
        "counter_map",
        "dimension_value_map",
        "event_map",
        "query_grouped_columns",
        "ratio_map",
    }

    def walk(value: Any, parent_key: str = "") -> None:
        if isinstance(value, dict):
            if value.get("enabled") is False or parent_key == "derived_metrics":
                return
            for key, item in value.items():
                if key == "scorecard_column" and isinstance(item, str):
                    metrics.add(item)
                elif key in mapping_keys and isinstance(item, dict):
                    metrics.update(
                        mapped for mapped in item.values() if isinstance(mapped, str)
                    )
                else:
                    walk(item, key)
        elif isinstance(value, list):
            for item in value:
                walk(item, parent_key)

    walk(config)
    return sorted(metrics)


def safe_source_fetch(
    source: str,
    fetch: Callable[[], SourceResult],
    metrics: list[str] | None = None,
) -> SourceResult:
    """Keep a source failure from stopping the run and name every affected metric."""
    try:
        result = fetch()
    except Exception as error:
        reason = " ".join(str(error).split()) or type(error).__name__
        affected = metrics or [f"values from {source}"]
        return SourceResult(
            source=source,
            implemented=False,
            notes=[
                f"Unable to fill {metric} due to {reason}." for metric in affected
            ],
        )

    returned_metrics = {
        metric
        for record in result.records
        for metric in record.get("values", {})
    }
    missing = [metric for metric in (metrics or []) if metric not in returned_metrics]
    if not missing:
        return result

    reason = " ".join(result.notes) or f"{source} returned no value"
    failure_notes = [
        f"Unable to fill {metric} due to {reason}." for metric in missing
    ]
    return SourceResult(
        source=result.source,
        implemented=result.implemented,
        records=result.records,
        notes=[*result.notes, *failure_notes],
    )


def safe_configured_source_fetch(
    source: str,
    config_path: str | Path,
    fetch: Callable[[], SourceResult],
) -> SourceResult:
    try:
        metrics = configured_scorecard_metrics(config_path)
    except Exception:
        metrics = []
    return safe_source_fetch(source, fetch, metrics)
