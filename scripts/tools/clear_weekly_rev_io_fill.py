from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.google_sheets_data import (  # noqa: E402
    SHEETS_API,
    authorized_request,
    get_values,
    make_credentials,
    spreadsheet_metadata,
    sheet_metadata_by_title,
)


TAB_NAME = "Weekly Media Data"
COLUMN_NAME = "Rev / IO"


def main() -> None:
    config = json.loads((ROOT / "config" / "scorecard.json").read_text())[
        "google_sheet"
    ]
    credentials = make_credentials(config["service_account_file"])
    spreadsheet_id = config["spreadsheet_id"]
    rows = get_values(credentials, spreadsheet_id, TAB_NAME)
    if not rows or COLUMN_NAME not in rows[0]:
        print(f"{TAB_NAME}: {COLUMN_NAME} column not found.")
        return

    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    sheet = sheet_metadata_by_title(metadata)[TAB_NAME]
    sheet_id = sheet["properties"]["sheetId"]
    column_index = rows[0].index(COLUMN_NAME)
    request = {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": len(rows),
                "startColumnIndex": column_index,
                "endColumnIndex": column_index + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColorStyle": None,
                }
            },
            "fields": "userEnteredFormat.backgroundColorStyle",
        }
    }
    authorized_request(
        credentials,
        f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
        method="POST",
        payload={"requests": [request]},
    )
    print(f"Cleared green fill from {TAB_NAME} / {COLUMN_NAME}.")


if __name__ == "__main__":
    main()
