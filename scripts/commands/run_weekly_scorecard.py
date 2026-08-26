from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lib.google_sheets_data import write_updates as write_google_sheet_updates
from pipelines.weekly_pipeline import records_to_updates
from sources.base import SourceResult, not_implemented_result
from sources.snapshots import DEFAULT_SNAPSHOT_FILE, apply_snapshot_mode
from sources import (
    ga4,
    hubspot,
    libsyn,
    personify,
    search_console,
    walsworth_thermostats,
    youtube,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCORECARD_CONFIG = PROJECT_ROOT / "config" / "scorecard.json"
DEFAULT_GA4_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "ga4.json"
DEFAULT_HUBSPOT_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "hubspot.json"
DEFAULT_YOUTUBE_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "youtube.json"
DEFAULT_LIBSYN_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "libsyn.json"
DEFAULT_SEARCH_CONSOLE_CONFIG = PROJECT_ROOT / "config" / "sources" / "shared" / "search_console.json"
SourceFetcher = Callable[[], SourceResult]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull all Weekly scorecard sources and write them to the shared Google Sheet."
    )
    parser.add_argument(
        "--scorecard-config",
        default=str(DEFAULT_SCORECARD_CONFIG),
        help="Path to config/scorecard.json.",
    )
    parser.add_argument("--ga4-config", default=str(DEFAULT_GA4_CONFIG))
    parser.add_argument("--hubspot-config", default=str(DEFAULT_HUBSPOT_CONFIG))
    parser.add_argument("--youtube-config", default=str(DEFAULT_YOUTUBE_CONFIG))
    parser.add_argument("--libsyn-config", default=str(DEFAULT_LIBSYN_CONFIG))
    parser.add_argument("--search-console-config", default=str(DEFAULT_SEARCH_CONSOLE_CONFIG))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned Google Sheet changes without saving.",
    )
    parser.add_argument(
        "--snapshot-file",
        default=str(DEFAULT_SNAPSHOT_FILE),
        help="Path to the source snapshot cache.",
    )
    parser.add_argument(
        "--refresh-snapshots",
        action="store_true",
        help="Replace saved snapshots for returned Weekly records with fresh source values.",
    )
    return parser.parse_args()


def load_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_weekly_or_placeholder(
    module: object,
    source_name: str,
    config: str | Path | None = None,
) -> SourceFetcher:
    fetch_weekly = getattr(module, "fetch_weekly", None)
    if not fetch_weekly:
        return lambda: not_implemented_result(source_name)
    if config is None:
        return fetch_weekly
    return lambda: fetch_weekly(config)


def weekly_source_fetchers(args: argparse.Namespace) -> list[SourceFetcher]:
    return [
        fetch_weekly_or_placeholder(ga4, "GA4", args.ga4_config),
        fetch_weekly_or_placeholder(walsworth_thermostats, "Walsworth Thermostats"),
        fetch_weekly_or_placeholder(personify, "Personify / Fonteva"),
        fetch_weekly_or_placeholder(libsyn, "Libsyn", args.libsyn_config),
        fetch_weekly_or_placeholder(youtube, "YouTube", args.youtube_config),
        fetch_weekly_or_placeholder(search_console, "Google Search Console", args.search_console_config),
        fetch_weekly_or_placeholder(hubspot, "HubSpot", args.hubspot_config),
    ]


def main() -> None:
    args = parse_args()
    scorecard_config = load_json(args.scorecard_config)
    google_sheet_config = scorecard_config["google_sheet"]

    all_records = []
    for fetch in weekly_source_fetchers(args):
        result = fetch()
        status = "implemented" if result.implemented else "not implemented"
        print(f"{result.source}: {status}")
        for note in result.notes:
            print(f"  - {note}")
        all_records.extend(result.records)

    if not all_records:
        print("No Weekly source records returned; Google Sheet was not changed.")
        return

    all_records, snapshot_notes = apply_snapshot_mode(
        all_records,
        cadence="weekly",
        snapshot_file=args.snapshot_file,
        create_missing=not args.dry_run,
        refresh=args.refresh_snapshots,
    )
    for note in snapshot_notes:
        print(f"Snapshot: {note}")

    updates = records_to_updates(all_records)
    changes, spreadsheet_id, spreadsheet_url = write_google_sheet_updates(
        google_sheet_config["service_account_file"],
        updates,
        "weekly",
        spreadsheet_id=google_sheet_config.get("spreadsheet_id"),
        title=google_sheet_config.get("title", "Scorecard"),
        dry_run=args.dry_run,
    )
    target_path = spreadsheet_url

    action = "Planned" if args.dry_run else "Wrote"
    print(f"{action} {len(changes)} Weekly changes in {target_path}")
    for change in changes:
        print(
            "  {sheet} [{date} | {column}]: {before!r} -> {after!r}".format(
                **change
            )
        )

if __name__ == "__main__":
    main()


