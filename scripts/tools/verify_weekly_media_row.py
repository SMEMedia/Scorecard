from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.google_sheets_data import SHEETS_API, authorized_request, make_credentials


TAB_NAME = "Weekly Media Data"
WATCH_COLUMNS = [
    "YouTube Video Plays",
    "Rev / IO",
]


def main() -> None:
    config = json.loads((ROOT / "config" / "scorecard.json").read_text())[
        "google_sheet"
    ]
    credentials = make_credentials(config["service_account_file"])
    spreadsheet_id = config["spreadsheet_id"]
    values_range = quote(f"'{TAB_NAME}'!A1:AZ1000", safe="")
    rows = authorized_request(
        credentials,
        f"{SHEETS_API}/{spreadsheet_id}/values/{values_range}?valueRenderOption=FORMATTED_VALUE&majorDimension=ROWS",
    ).get("values", [])
    headers = rows[0]
    row = rows[-1]
    row_number = len(rows)

    fields = "sheets(data(rowData(values(userEnteredFormat(backgroundColorStyle,backgroundColor)))))"
    metadata = authorized_request(
        credentials,
        (
            f"{SHEETS_API}/{spreadsheet_id}?includeGridData=true"
            f"&ranges={quote(f'{TAB_NAME}!A{row_number}:AZ{row_number}', safe='')}"
            f"&fields={quote(fields, safe='(),')}"
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
