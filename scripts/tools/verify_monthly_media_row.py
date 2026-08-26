from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.google_sheets_data import SHEETS_API, authorized_request, make_credentials


TAB_NAME = "Monthly Media Data"
WATCH_COLUMNS = [
    "Total App Downloads",
    "Podcast Total",
    "Email Open Rate",
    "Email CTR",
    "Email Click to Open Rate",
    "YouTube Video Plays",
    "GA4 Search Clicks",
    "GA4 Search Impressions",
    "Google Search Console Search Clicks",
    "Google Search Console Search Impressions",
    "Email Starts",
    "Email Stops",
    "Email Net Subs",
]


def main() -> None:
    config = json.loads((ROOT / "config" / "scorecard.json").read_text())
    sheet_config = config["google_sheet"]
    credentials = make_credentials(sheet_config["service_account_file"])
    spreadsheet_id = sheet_config["spreadsheet_id"]

    values_range = quote(f"'{TAB_NAME}'!A1:BC1000", safe="")
    values = authorized_request(
        credentials,
        f"{SHEETS_API}/{spreadsheet_id}/values/{values_range}?valueRenderOption=FORMATTED_VALUE&majorDimension=ROWS",
    ).get("values", [])
    headers = values[0]
    row = values[-1]
    row_number = len(values)

    fields = "sheets(data(rowData(values(userEnteredFormat(backgroundColorStyle,backgroundColor)))))"
    grid_range = quote(f"{TAB_NAME}!A{row_number}:BC{row_number}", safe="")
    metadata = authorized_request(
        credentials,
        (
            f"{SHEETS_API}/{spreadsheet_id}?includeGridData=true"
            f"&ranges={grid_range}&fields={quote(fields, safe='(),')}"
        ),
    )
    cells = (
        metadata.get("sheets", [{}])[0]
        .get("data", [{}])[0]
        .get("rowData", [{}])[0]
        .get("values", [])
    )

    print(f"{TAB_NAME} row {row_number} ({row[0]})")
    for column in WATCH_COLUMNS:
        index = headers.index(column)
        value = row[index] if index < len(row) else ""
        cell = cells[index] if index < len(cells) else {}
        format_ = cell.get("userEnteredFormat", {})
        color = (
            format_.get("backgroundColorStyle", {}).get("rgbColor")
            or format_.get("backgroundColor")
            or {}
        )
        is_green = (
            round(color.get("red", -1), 4) == 0.8863
            and round(color.get("green", -1), 4) == 0.9373
            and round(color.get("blue", -1), 4) == 0.8588
        )
        print(f"{column}: {value!r}, green={is_green}")


if __name__ == "__main__":
    main()
