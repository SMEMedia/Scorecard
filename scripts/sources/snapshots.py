from __future__ import annotations

import json
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_FILE = PROJECT_ROOT / "config" / "state" / "scorecard_snapshots.json"


def _snapshot_key(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("source", "")),
        str(record.get("report", "")),
        str(record.get("sheet", "")),
        str(record.get("date_column", "")),
        str(record.get("date", "")),
    ]
    return " | ".join(parts)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, time):
        return {
            "__type": "time",
            "value": value.isoformat(),
        }
    return value


def _deserialize_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__type") == "time":
        return time.fromisoformat(value["value"])
    return value


def _serialize_record(record: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(record)
    serialized["values"] = {
        key: _serialize_value(value)
        for key, value in record.get("values", {}).items()
    }
    return serialized


def _deserialize_record(record: dict[str, Any]) -> dict[str, Any]:
    deserialized = dict(record)
    deserialized["values"] = {
        key: _deserialize_value(value)
        for key, value in record.get("values", {}).items()
    }
    return deserialized


def load_snapshot_file(path: str | Path | None = None) -> dict[str, Any]:
    snapshot_path = Path(path or DEFAULT_SNAPSHOT_FILE)
    if not snapshot_path.exists():
        return {"snapshots": {}}
    raw = snapshot_path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"snapshots": {}}
    payload = json.loads(raw)
    if "snapshots" not in payload or not isinstance(payload["snapshots"], dict):
        payload["snapshots"] = {}
    return payload


def save_snapshot_file(payload: dict[str, Any], path: str | Path | None = None) -> None:
    snapshot_path = Path(path or DEFAULT_SNAPSHOT_FILE)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def apply_snapshot_mode(
    records: list[dict[str, Any]],
    cadence: str,
    snapshot_file: str | Path | None = None,
    create_missing: bool = True,
    refresh: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Freeze source records by source/report/sheet/date.

    Existing snapshots always win unless refresh=True. Missing snapshots are
    created only when create_missing=True, keeping dry runs side-effect-free.
    """

    payload = load_snapshot_file(snapshot_file)
    snapshots = payload["snapshots"]
    now = datetime.now(timezone.utc).isoformat()
    output = []
    notes = []
    changed = False
    used = 0
    created = 0
    refreshed = 0
    missing = 0

    for record in records:
        key = _snapshot_key(record)
        existed_before = key in snapshots
        saved_record = snapshots.get(key, {}).get("record", {})
        saved_values = saved_record.get("values", {})
        record_values = record.get("values", {})
        should_replace_empty_snapshot = (
            existed_before
            and not refresh
            and not saved_values
            and bool(record_values)
        )
        if key in snapshots and not refresh and not should_replace_empty_snapshot:
            output.append(_deserialize_record(snapshots[key]["record"]))
            used += 1
            continue

        output.append(record)
        if create_missing:
            snapshots[key] = {
                "cadence": cadence,
                "captured_at": now,
                "record": _serialize_record(record),
            }
            changed = True
            if existed_before and refresh:
                refreshed += 1
            elif should_replace_empty_snapshot:
                refreshed += 1
            else:
                created += 1
        else:
            missing += 1

    if changed:
        save_snapshot_file(payload, snapshot_file)

    if used:
        notes.append(f"Snapshot mode reused {used} saved {cadence} record(s).")
    if created:
        notes.append(f"Snapshot mode created {created} saved {cadence} record(s).")
    if refreshed:
        notes.append(f"Snapshot mode refreshed {refreshed} saved {cadence} record(s).")
    if missing:
        notes.append(
            f"Snapshot mode saw {missing} unsaved {cadence} record(s); dry run did not create snapshots."
        )
    if records and not notes:
        notes.append(f"Snapshot mode checked {len(records)} {cadence} record(s).")

    return output, notes
