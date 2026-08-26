from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.google_sheets_data import (
    SHEETS_API,
    authorized_request,
    make_credentials,
    spreadsheet_metadata,
)


TAB_NAME = "Monthly Media Data"
WATCH_COLUMNS = [
    "AM Sessions",
    "AM Page Views",
    "AM Users",
    "AM New Users",
    "AM Return Users",
    "AM New User %%",
    "AM Return User %%",
    "AM Sessions / User",
    "AM Page Views / Session",
    "Monthly App Downloads",
    "Total App Downloads",
    "Podcast Downloads",
    "YouTube Podcast Plays",
    "AM Web Podcast Plays",
    "Podcast Total",
    "YouTube Video Plays",
    "Email Subscribers",
    "Emails Delivered",
    "Email Opens",
    "Email Open Rate",
    "Email Clicks",
    "Email CTR",
    "Email Click to Open Rate",
    "Email Starts",
    "Email Stops",
    "Email Net Subs",
    "YouTube Subscribers",
]


def main() -> None:
    config = json.loads((ROOT / "config" / "scorecard.json").read_text())
    sheet_config = config["google_sheet"]
    credentials = make_credentials(sheet_config["service_account_file"])
    spreadsheet_id = sheet_config["spreadsheet_id"]
    range_name = quote(f"'{TAB_NAME}'!A1:BC1000", safe="")
    payload = authorized_request(
        credentials,
        f"{SHEETS_API}/{spreadsheet_id}/values/{range_name}?valueRenderOption=FORMULA&majorDimension=ROWS",
    )
    rows = payload.get("values", [])
    headers = rows[0]
    indexes = {header: index for index, header in enumerate(headers)}
    for row_number, row in list(enumerate(rows, start=1))[-8:]:
        print(f"ROW {row_number}: {row[0] if row else ''}")
        for column in WATCH_COLUMNS:
            if column not in indexes:
                continue
            index = indexes[column]
            value = row[index] if index < len(row) else ""
            print(f"  {column}: {value}")

    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    sheet_id = next(
        sheet["properties"]["sheetId"]
        for sheet in metadata["sheets"]
        if sheet["properties"]["title"] == TAB_NAME
    )
    last_row_index = len(rows) - 1
    fields = "sheets(data(rowData(values(userEnteredValue,effectiveValue,formattedValue))))"
    grid_payload = authorized_request(
        credentials,
        (
            f"{SHEETS_API}/{spreadsheet_id}?includeGridData=true"
            f"&ranges={quote(f'{TAB_NAME}!A{last_row_index + 1}:BC{last_row_index + 1}', safe='')}"
            f"&fields={quote(fields, safe='(),')}"
        ),
    )
    values = (
        grid_payload.get("sheets", [{}])[0]
        .get("data", [{}])[0]
        .get("rowData", [{}])[0]
        .get("values", [])
    )
    print("LAST ROW CELL METADATA")
    for column in WATCH_COLUMNS:
        if column not in indexes:
            continue
        index = indexes[column]
        cell = values[index] if index < len(values) else {}
        print(
            f"  {column}: user={cell.get('userEnteredValue')} "
            f"effective={cell.get('effectiveValue')} formatted={cell.get('formattedValue')!r}"
        )


if __name__ == "__main__":
    main()
