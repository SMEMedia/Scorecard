from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lib.google_sheets_data import write_updates
from pipelines.monthly_pipeline import records_to_updates
from sources.ga4 import fetch_monthly


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCORECARD_CONFIG = PROJECT_ROOT / "config" / "scorecard.json"
DEFAULT_GA4_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "ga4.json"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch GA4 monthly records and write them to the shared Google Scorecard sheet."
    )
    parser.add_argument(
        "--scorecard-config",
        default=str(DEFAULT_SCORECARD_CONFIG),
        help="Path to config/scorecard.json.",
    )
    parser.add_argument(
        "--ga4-config",
        default=str(DEFAULT_GA4_CONFIG),
        help="Path to the monthly GA4 config.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned Google Sheet changes without saving.",
    )
    return parser.parse_args()


def load_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    args = parse_args()
    scorecard_config = load_json(args.scorecard_config)
    google_sheet_config = scorecard_config["google_sheet"]

    result = fetch_monthly(args.ga4_config)
    for note in result.notes:
        print(f"GA4: {note}")

    if not result.records:
        print("No GA4 records returned; Google Sheet was not changed.")
        return

    changes, spreadsheet_id, spreadsheet_url = write_updates(
        google_sheet_config["service_account_file"],
        records_to_updates(result.records),
        "monthly",
        spreadsheet_id=google_sheet_config.get("spreadsheet_id"),
        title=google_sheet_config.get("title", "Scorecard"),
        dry_run=args.dry_run,
    )
    action = "Planned" if args.dry_run else "Wrote"
    print(f"{action} {len(changes)} GA4 changes in {spreadsheet_url}")
    for change in changes:
        print(
            "  {sheet} [{date} | {column}]: {before!r} -> {after!r}".format(
                **change
            )
        )


if __name__ == "__main__":
    main()
