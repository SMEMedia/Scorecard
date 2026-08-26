from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

try:
    from .base import SourceResult
    from .weekly_utils import weekly_date_range
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult
    from sources.weekly_utils import weekly_date_range


SOURCE_NAME = "Google Search Console"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "shared" / "search_console.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "search_console.json"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
SEARCH_ANALYTICS_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site_url}/searchAnalytics/query"


class ConfigError(ValueError):
    pass


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_SEARCH_CONSOLE_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def service_account_file(config: dict[str, Any]) -> str:
    path = config.get("service_account_file")
    if not path:
        raise ConfigError("Search Console service_account_file is not configured.")
    if not Path(path).exists():
        raise ConfigError(f"Search Console service account file does not exist: {path}")
    return path


def make_credentials(config: dict[str, Any]) -> service_account.Credentials:
    return service_account.Credentials.from_service_account_file(
        service_account_file(config),
        scopes=[SCOPE],
    )


def monthly_date_range(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("default_date_range")
    if not raw:
        raise ConfigError("Search Console config needs default_date_range.")

    if raw.get("mode") == "latest_completed_month":
        today = date.today()
        first_of_current_month = date(today.year, today.month, 1)
        last_of_previous_month = date.fromordinal(first_of_current_month.toordinal() - 1)
        start = date(last_of_previous_month.year, last_of_previous_month.month, 1)
        return {
            "start_date": start.isoformat(),
            "end_date": last_of_previous_month.isoformat(),
            "scorecard_date": start.isoformat(),
        }

    if "start_date" not in raw or "end_date" not in raw:
        raise ConfigError("Date range needs start_date/end_date or a supported mode.")
    start = datetime.fromisoformat(raw["start_date"]).date()
    return {
        "start_date": raw["start_date"],
        "end_date": raw["end_date"],
        "scorecard_date": date(start.year, start.month, 1).isoformat(),
    }


def scorecard_values(api_values: dict[str, int | float], columns: dict[str, str]) -> dict[str, int | float]:
    values: dict[str, int | float] = {}
    if "clicks" in columns:
        values[columns["clicks"]] = int(api_values.get("clicks", 0))
    if "impressions" in columns:
        values[columns["impressions"]] = int(api_values.get("impressions", 0))
    if "position" in columns:
        values[columns["position"]] = float(api_values.get("position", 0))
    if "ctr" in columns:
        values[columns["ctr"]] = float(api_values.get("ctr", 0))
    return values


def query_search_analytics(
    credentials: service_account.Credentials,
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: list[str] | None = None,
) -> dict[str, int | float]:
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())

    encoded_site = quote(site_url, safe="")
    all_rows = []
    start_row = 0
    row_limit = 25000
    while True:
        request = Request(
            SEARCH_ANALYTICS_URL.format(site_url=encoded_site),
            data=json.dumps(
                {
                "startDate": start_date,
                "endDate": end_date,
                "aggregationType": "auto",
                "dimensions": dimensions or [],
                    "rowLimit": row_limit,
                    "startRow": start_row,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("rows") or []
        all_rows.extend(rows)
        if not dimensions or len(rows) < row_limit:
            break
        start_row += row_limit
    rows = all_rows
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
    if dimensions:
        clicks = sum(float(row.get("clicks", 0)) for row in rows)
        impressions = sum(float(row.get("impressions", 0)) for row in rows)
        weighted_position_total = sum(
            float(row.get("position", 0)) * float(row.get("impressions", 0))
            for row in rows
        )
        return {
            "clicks": int(clicks),
            "impressions": int(impressions),
            "ctr": clicks / impressions if impressions else 0.0,
            "position": weighted_position_total / impressions if impressions else 0.0,
        }
    return rows[0]


def build_record(
    config: dict[str, Any],
    section: dict[str, Any],
    date_info: dict[str, str],
    api_values: dict[str, int | float],
    report_name: str,
) -> dict[str, Any]:
    return {
        "source": SOURCE_NAME,
        "report": report_name,
        "sheet": section["sheet"],
        "date_column": section["date_column"],
        "date": date_info["scorecard_date"],
        "values": scorecard_values(api_values, section["columns"]),
    }


def query_grouped_record(
    config: dict[str, Any],
    section: dict[str, Any],
    date_info: dict[str, str],
    api_values: dict[str, int | float],
    report_name: str,
) -> dict[str, Any]:
    return build_record(
        config,
        {
            **section,
            "columns": section.get("query_grouped_columns", {}),
        },
        date_info,
        api_values,
        report_name,
    )


def api_error_note(error: HTTPError | URLError) -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        api_error = payload.get("error", {})
        message = api_error.get("message") or body or error.reason
        for detail in api_error.get("details", []):
            activation_url = detail.get("metadata", {}).get("activationUrl")
            if activation_url:
                return f"Search Console API error {error.code}: {message} Enable here: {activation_url}"
        return f"Search Console API error {error.code}: {message}"
    return f"Search Console connection error: {error.reason}"


def fetch_monthly(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Search Console config does not exist at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure site_url.",
            ],
        )

    try:
        section = config.get("monthly", {})
        if not section.get("enabled", False):
            return SourceResult(source=SOURCE_NAME, implemented=False, notes=["Monthly Search Console source is disabled in config."])
        site_url = config.get("site_url")
        if not site_url:
            raise ConfigError("Search Console site_url is not configured.")
        date_info = monthly_date_range(config)
        values = query_search_analytics(
            make_credentials(config),
            site_url,
            date_info["start_date"],
            date_info["end_date"],
        )
        records = [build_record(config, section, date_info, values, "monthly_search_performance")]
        if section.get("query_grouped_columns"):
            query_values = query_search_analytics(
                make_credentials(config),
                site_url,
                date_info["start_date"],
                date_info["end_date"],
                ["query"],
            )
            records.append(
                query_grouped_record(
                    config,
                    section,
                    date_info,
                    query_values,
                    "monthly_search_queries",
                )
            )
        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=records,
            notes=[
                f"Loaded Search Console config from {loaded_path}.",
                f"Queried {site_url} from {date_info['start_date']} to {date_info['end_date']}.",
            ],
        )
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def fetch_weekly(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Search Console config does not exist at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure site_url.",
            ],
        )

    try:
        section = config.get("weekly", {})
        if not section.get("enabled", False):
            return SourceResult(source=SOURCE_NAME, implemented=False, notes=["Weekly Search Console source is disabled in config."])
        site_url = config.get("site_url")
        if not site_url:
            raise ConfigError("Search Console site_url is not configured.")
        date_info = weekly_date_range(week_ending_weekday=int(section.get("week_ending_weekday", 5)))
        values = query_search_analytics(
            make_credentials(config),
            site_url,
            date_info["start_date"],
            date_info["end_date"],
        )
        records = [build_record(config, section, date_info, values, "weekly_search_performance")]
        if section.get("query_grouped_columns"):
            query_values = query_search_analytics(
                make_credentials(config),
                site_url,
                date_info["start_date"],
                date_info["end_date"],
                ["query"],
            )
            records.append(
                query_grouped_record(
                    config,
                    section,
                    date_info,
                    query_values,
                    "weekly_search_queries",
                )
            )
        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=records,
            notes=[
                f"Loaded Search Console config from {loaded_path}.",
                f"Queried {site_url} from {date_info['start_date']} to {date_info['end_date']}.",
            ],
        )
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Google Search Console scorecard data.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--weekly", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = fetch_weekly(args.config) if args.weekly else fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
