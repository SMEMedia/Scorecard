from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from sources.base import SourceResult
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
        description="Run all monthly scorecard source integrations."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Reserved for future write behavior. Current scaffold never writes.",
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
    return parser.parse_args()


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
    if args.dry_run:
        print("Dry run requested. Current scaffold does not write in any mode.")

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


if __name__ == "__main__":
    main()
