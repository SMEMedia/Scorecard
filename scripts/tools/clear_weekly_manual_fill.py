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
from scripts.pipelines.weekly_pipeline import MANUAL_COLUMNS  # noqa: E402


TAB_NAME = "Weekly Media Data"


def main() -> None:
    config = json.loads((ROOT / "config" / "scorecard.json").read_text())["google_sheet"]
    credentials = make_credentials(config["service_account_file"])
    spreadsheet_id = config["spreadsheet_id"]
    rows = get_values(credentials, spreadsheet_id, TAB_NAME)
    if not rows:
        print(f"{TAB_NAME}: no rows found.")
        return

    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    sheet_id = sheet_metadata_by_title(metadata)[TAB_NAME]["properties"]["sheetId"]
    headers = rows[0]
    requests = []
    cleared = []
    for column in sorted(MANUAL_COLUMNS["SME Media Data"]):
        if column not in headers:
            continue
        column_index = headers.index(column)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": len(rows),
                        "startColumnIndex": column_index,
                        "endColumnIndex": column_index + 1,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColorStyle": None}},
                    "fields": "userEnteredFormat.backgroundColorStyle",
                }
            }
        )
        cleared.append(column)

    if requests:
        authorized_request(
            credentials,
            f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
            method="POST",
            payload={"requests": requests},
        )
    print(f"Cleared fill from {len(cleared)} manual Weekly Media Data columns.")


if __name__ == "__main__":
    main()
