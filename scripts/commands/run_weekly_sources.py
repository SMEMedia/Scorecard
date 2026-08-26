from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from sources.base import SourceResult, not_implemented_result
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
DEFAULT_GA4_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "ga4.json"
DEFAULT_HUBSPOT_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "hubspot.json"
DEFAULT_YOUTUBE_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "youtube.json"
DEFAULT_LIBSYN_CONFIG = PROJECT_ROOT / "config" / "sources" / "weekly" / "libsyn.json"
DEFAULT_SEARCH_CONSOLE_CONFIG = PROJECT_ROOT / "config" / "sources" / "shared" / "search_console.json"
SourceFetcher = Callable[[], SourceResult]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all Weekly scorecard source integrations."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Reserved for future write behavior. This command never writes.",
    )
    parser.add_argument("--ga4-config", default=str(DEFAULT_GA4_CONFIG))
    parser.add_argument("--hubspot-config", default=str(DEFAULT_HUBSPOT_CONFIG))
    parser.add_argument("--youtube-config", default=str(DEFAULT_YOUTUBE_CONFIG))
    parser.add_argument("--libsyn-config", default=str(DEFAULT_LIBSYN_CONFIG))
    parser.add_argument("--search-console-config", default=str(DEFAULT_SEARCH_CONSOLE_CONFIG))
    return parser.parse_args()


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
    if args.dry_run:
        print("Dry run requested. This source-status command does not write in any mode.")

    for fetch in weekly_source_fetchers(args):
        result = fetch()
        status = "implemented" if result.implemented else "not implemented"
        print(f"{result.source}: {status}")
        for note in result.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
