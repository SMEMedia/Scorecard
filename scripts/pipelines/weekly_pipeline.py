from __future__ import annotations

from typing import Any


WEEKLY_TABLE_BY_SHEET = {
    "SME Media Data": "Table1",
}

WORKBOOK_FORMULA_COLUMNS = {
    "SME Media Data": {
        "AM New User %%",
        "AM Return User %%",
        "AM Sessions / User",
        "AM Page Views / Session",
        "Podcast Total",
        "Email Open Rate",
        "Email CTR",
        "Email Click to Open Rate",
    },
}

MANUAL_COLUMNS = {
    "SME Media Data": {
        "New IOs (Count)",
        "New IOs (Revenue)",
        "Rev / IO",
        "Pipeline (10)",
        "Pipeline (10v)",
        "Pipeline (50)",
        "Pipeline (50v)",
        "Pipeline (90)",
        "Pipeline (90v)",
        "Pipeline Total",
        "Pipeline Total (Tv)",
    },
}


def records_to_updates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updates = []
    for record in records:
        sheet = record["sheet"]
        if sheet not in WEEKLY_TABLE_BY_SHEET:
            raise ValueError(f"No Weekly table mapping configured for sheet: {sheet}")

        values = {
            header: value
            for header, value in record.get("values", {}).items()
            if header not in WORKBOOK_FORMULA_COLUMNS.get(sheet, set())
            and header not in MANUAL_COLUMNS.get(sheet, set())
        }
        if not values:
            continue

        updates.append(
            {
                "sheet": sheet,
                "table": WEEKLY_TABLE_BY_SHEET[sheet],
                "date_column": record["date_column"],
                "date": record["date"],
                "values": values,
                "formula_columns": sorted(WORKBOOK_FORMULA_COLUMNS.get(sheet, set())),
                "add_missing_dates": True,
                "date_step_days": 7,
            }
        )
    return updates
