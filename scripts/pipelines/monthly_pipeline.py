from __future__ import annotations

from datetime import time
from typing import Any


MONTHLY_TABLE_BY_SHEET = {
    "SME Media Data": "Table1",
    "SME Media Data (Detail)": "Table14",
    "SME Media Engagement Metrics": "Table147",
}

WORKBOOK_FORMULA_COLUMNS = {
    "SME Media Data": {
        "AM New User %%",
        "AM Return User %%",
        "AM Sessions / User",
        "AM Page Views / Session",
        "Total App Downloads",
        "Podcast Total",
        "Email Open Rate",
        "Email CTR",
        "Email Click to Open Rate",
        "Email Net Subs",
    },

}

WORKBOOK_FORMULA_TEMPLATES = {
    "SME Media Data": {
        "Total App Downloads": "=SUM($[[Monthly App Downloads]]${data_start_row}:[[Monthly App Downloads]]{row})",
    },
}


def _duration_text(value: Any) -> str:
    if isinstance(value, time):
        duration = f"{value.hour}:{value.minute:02d}:{value.second:02d}"
    elif isinstance(value, (int, float)):
        total_seconds = round(float(value) * 86400)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        duration = f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        duration = str(value).lstrip("'")
        if duration.count(":") == 2 and duration.startswith("0"):
            duration = duration[1:]
    return "'" + duration


def _numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _records_with_derived_automation(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    youtube_views_by_date: dict[str, float] = {}
    youtube_podcast_by_date: dict[str, float] = {}
    media_values_by_date: dict[str, dict[str, Any]] = {}
    engagement_values_by_date: dict[str, dict[str, Any]] = {}
    for record in records:
        date = str(record.get("date"))
        values = record.get("values", {})
        if record.get("sheet") == "SME Media Engagement Metrics":
            engagement_values_by_date.setdefault(date, {}).update(values)
            views = _numeric(values.get("Videos Views*"))
            if views is not None:
                youtube_views_by_date[date] = views
        if record.get("sheet") == "SME Media Data":
            media_values_by_date.setdefault(date, {}).update(values)
            podcast = _numeric(values.get("YouTube Podcast Plays"))
            if podcast is not None:
                youtube_podcast_by_date[date] = podcast

    derived_records = []
    for date, views in youtube_views_by_date.items():
        podcast = youtube_podcast_by_date.get(date)
        if podcast is None:
            continue
        derived_records.append(
            {
                "source": "Derived",
                "report": "monthly_youtube_video_plays",
                "sheet": "SME Media Data",
                "date_column": "Month",
                "date": date,
                "values": {
                    "YouTube Video Plays": max(views - podcast, 0),
                },
            }
        )

    for date, engagement_values in engagement_values_by_date.items():
        total_users = _numeric(engagement_values.get("AM.org Total Users (#)"))
        return_users = _numeric(
            media_values_by_date.get(date, {}).get("AM Return Users")
        )
        if total_users in (None, 0) or return_users is None:
            continue
        derived_records.append(
            {
                "source": "Derived",
                "report": "monthly_engagement_returning_users",
                "sheet": "SME Media Engagement Metrics",
                "date_column": "Month",
                "date": date,
                "values": {
                    "AM.org Return Users (#)": return_users,
                    "AM.org Return Users (%)": return_users / total_users,
                },
            }
        )
    return records + derived_records


def records_to_updates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updates = []
    for record in _records_with_derived_automation(records):
        sheet = record["sheet"]
        if sheet not in MONTHLY_TABLE_BY_SHEET:
            raise ValueError(f"No Monthly table mapping configured for sheet: {sheet}")

        values = {}
        for header, value in record.get("values", {}).items():
            if header in WORKBOOK_FORMULA_COLUMNS.get(sheet, set()):
                continue
            if header == "Avg. View Duration*":
                value = _duration_text(value)
            values[header] = value
        if not values:
            continue

        updates.append(
            {
                "sheet": sheet,
                "table": MONTHLY_TABLE_BY_SHEET[sheet],
                "date_column": record["date_column"],
                "date": record["date"],
                "values": values,
                "formula_columns": sorted(WORKBOOK_FORMULA_COLUMNS.get(sheet, set())),
                "formula_templates": WORKBOOK_FORMULA_TEMPLATES.get(sheet, {}),
                "add_missing_dates": True,
            }
        )
    return updates


