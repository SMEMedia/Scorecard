from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.google_sheets_data import get_values, make_credentials, normalize_date


WATCH_COLUMNS = [
    "Email Subscribers",
    "Podcast Downloads",
    "YouTube Podcast Plays",
    "AM Web Podcast Plays",
    "Podcast Total",
    "YouTube Video Plays",
    "AM Users",
    "AM Sessions",
    "New IOs (Count)",
    "New IOs (Revenue)",
]


def in_range(value: object, start: date, end: date) -> bool:
    try:
        parsed = normalize_date(value)
    except Exception:
        return False
    return start <= parsed <= end


def print_rows(tab_name: str, start: date, end: date) -> None:
    config = json.loads((ROOT / "config" / "scorecard.json").read_text())[
        "google_sheet"
    ]
    credentials = make_credentials(config["service_account_file"])
    rows = get_values(credentials, config["spreadsheet_id"], tab_name)
    if not rows:
        print(f"{tab_name}: no rows")
        return
    headers = rows[0]
    indexes = {header: index for index, header in enumerate(headers)}
    columns = [column for column in WATCH_COLUMNS if column in indexes]
    print(f"\n{tab_name}")
    print(["Date", *columns])
    for row in rows[1:]:
        if not row or not in_range(row[0], start, end):
            continue
        output = [row[0]]
        for column in columns:
            index = indexes[column]
            output.append(row[index] if index < len(row) else "")
        print(output)


def main() -> None:
    start = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    end = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    print_rows("Monthly Media Data", start, end)
    print_rows("Weekly Media Data", start, end)


if __name__ == "__main__":
    main()
