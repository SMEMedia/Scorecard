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
from pipelines.monthly_pipeline import records_to_updates
from sources.base import SourceResult
from sources.snapshots import DEFAULT_SNAPSHOT_FILE, apply_snapshot_mode
from sources import (
    app_stores,
    ga4,
    hubspot,
    linkedin_analytics,
    libsyn,
    meta_social,
    personify,
    search_console,
    walsworth_thermostats,
    x_social,
    youtube,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCORECARD_CONFIG = PROJECT_ROOT / "config" / "scorecard.json"
DEFAULT_GA4_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "ga4.json"
DEFAULT_HUBSPOT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "hubspot.json"
DEFAULT_GOOGLE_PLAY_CONFIG = PROJECT_ROOT / "config" / "sources" / "optional" / "google_play.json"
DEFAULT_YOUTUBE_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "youtube.json"
DEFAULT_META_SOCIAL_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "meta.json"
DEFAULT_X_SOCIAL_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "x.json"
DEFAULT_LIBSYN_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "libsyn.json"
DEFAULT_SEARCH_CONSOLE_CONFIG = PROJECT_ROOT / "config" / "sources" / "shared" / "search_console.json"

SourceFetcher = Callable[[], SourceResult]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull all monthly scorecard sources and write them to the shared Google Sheet."
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
        "--hubspot-config",
        default=str(DEFAULT_HUBSPOT_CONFIG),
        help="Path to the monthly HubSpot config.",
    )
    parser.add_argument(
        "--google-play-config",
        default=str(DEFAULT_GOOGLE_PLAY_CONFIG),
        help="Path to the optional app-store config.",
    )
    parser.add_argument(
        "--youtube-config",
        default=str(DEFAULT_YOUTUBE_CONFIG),
        help="Path to the monthly YouTube config.",
    )
    parser.add_argument(
        "--meta-social-config",
        default=str(DEFAULT_META_SOCIAL_CONFIG),
        help="Path to the monthly Meta config.",
    )
    parser.add_argument(
        "--x-social-config",
        default=str(DEFAULT_X_SOCIAL_CONFIG),
        help="Path to the monthly X config.",
    )
    parser.add_argument(
        "--libsyn-config",
        default=str(DEFAULT_LIBSYN_CONFIG),
        help="Path to the monthly Libsyn config.",
    )
    parser.add_argument(
        "--search-console-config",
        default=str(DEFAULT_SEARCH_CONSOLE_CONFIG),
        help="Path to the shared Search Console config.",
    )
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
        help="Replace saved snapshots for returned monthly records with fresh source values.",
    )
    return parser.parse_args()


def load_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def monthly_source_fetchers(
    ga4_config: str | Path,
    hubspot_config: str | Path,
    google_play_config: str | Path,
    youtube_config: str | Path,
    meta_social_config: str | Path,
    x_social_config: str | Path,
    libsyn_config: str | Path,
    search_console_config: str | Path,
) -> list[SourceFetcher]:
    return [
        lambda: ga4.fetch_monthly(ga4_config),
        walsworth_thermostats.fetch_monthly,
        personify.fetch_monthly,
        lambda: app_stores.fetch_monthly(google_play_config),
        lambda: libsyn.fetch_monthly(libsyn_config),
        lambda: youtube.fetch_monthly(youtube_config),
        lambda: search_console.fetch_monthly(search_console_config),
        lambda: hubspot.fetch_monthly(hubspot_config),
        lambda: meta_social.fetch_monthly(meta_social_config),
        lambda: x_social.fetch_monthly(x_social_config),
        linkedin_analytics.fetch_monthly,
    ]


def main() -> None:
    args = parse_args()
    scorecard_config = load_json(args.scorecard_config)
    google_sheet_config = scorecard_config["google_sheet"]

    all_records = []
    for fetch in monthly_source_fetchers(
        args.ga4_config,
        args.hubspot_config,
        args.google_play_config,
        args.youtube_config,
        args.meta_social_config,
        args.x_social_config,
        args.libsyn_config,
        args.search_console_config,
    ):
        result = fetch()
        status = "implemented" if result.implemented else "not implemented"
        print(f"{result.source}: {status}")
        for note in result.notes:
            print(f"  - {note}")
        all_records.extend(result.records)

    if not all_records:
        print("No source records returned; Google Sheet was not changed.")
        return

    all_records, snapshot_notes = apply_snapshot_mode(
        all_records,
        cadence="monthly",
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
        "monthly",
        spreadsheet_id=google_sheet_config.get("spreadsheet_id"),
        title=google_sheet_config.get("title", "Scorecard"),
        dry_run=args.dry_run,
    )
    target_path = spreadsheet_url

    action = "Planned" if args.dry_run else "Wrote"
    print(f"{action} {len(changes)} monthly changes in {target_path}")
    for change in changes:
        print(
            "  {sheet} [{date} | {column}]: {before!r} -> {after!r}".format(
                **change
            )
        )

if __name__ == "__main__":
    main()


