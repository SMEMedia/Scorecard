from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lib.google_sheets_data import (
    SHEETS_API,
    authorized_request,
    make_credentials,
    spreadsheet_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCORECARD_CONFIG = PROJECT_ROOT / "config" / "scorecard.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear automation green fill from all Google Scorecard table body cells."
    )
    parser.add_argument("--scorecard-config", default=str(DEFAULT_SCORECARD_CONFIG))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.scorecard_config, "r", encoding="utf-8") as handle:
        config = json.load(handle)["google_sheet"]

    credentials = make_credentials(config["service_account_file"])
    metadata = spreadsheet_metadata(credentials, config["spreadsheet_id"])
    requests = []

    for sheet in metadata.get("sheets", []):
        for table in sheet.get("tables") or []:
            table_range = table["range"]
            if table_range.get("endRowIndex", 0) <= 1:
                continue
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": table_range["sheetId"],
                            "startRowIndex": 1,
                            "endRowIndex": table_range["endRowIndex"],
                            "startColumnIndex": table_range.get("startColumnIndex", 0),
                            "endColumnIndex": table_range["endColumnIndex"],
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColorStyle": None
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColorStyle",
                    }
                }
            )

    if requests:
        authorized_request(
            credentials,
            f"{SHEETS_API}/{config['spreadsheet_id']}:batchUpdate",
            method="POST",
            payload={"requests": requests},
        )
    print(f"Cleared automation fill from {config['title']}")


if __name__ == "__main__":
    main()
