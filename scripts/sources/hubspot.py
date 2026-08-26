from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from .base import SourceResult
    from .weekly_utils import weekly_date_range
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult
    from sources.weekly_utils import weekly_date_range


SOURCE_NAME = "HubSpot"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "hubspot.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "hubspot.json"
API_BASE = "https://api.hubapi.com"
SENT_EMAIL_STATES = {"PUBLISHED", "PUBLISHED_AB", "PUBLISHED_AB_VARIANT"}


class ConfigError(ValueError):
    pass


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_HUBSPOT_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def token_file(config: dict[str, Any]) -> Path:
    if config.get("private_app_token_file"):
        path = Path(config["private_app_token_file"])
    elif config.get("private_app_token_file_env"):
        path = Path(required_env(config["private_app_token_file_env"]))
    else:
        raise ConfigError(
            "HubSpot config needs private_app_token_file or private_app_token_file_env."
        )

    if not path.exists():
        raise ConfigError(f"HubSpot token file does not exist: {path}")
    return path


def load_token(config: dict[str, Any]) -> str:
    token = token_file(config).read_text(encoding="utf-8").strip()
    if not token:
        raise ConfigError("HubSpot token file is empty.")
    return token


def date_range_config(config: dict[str, Any], report: dict[str, Any]) -> dict[str, str]:
    raw = report.get("date_range") or config.get("default_date_range")
    if not raw:
        raise ConfigError(f"Report {report.get('name', '<unnamed>')} needs a date range.")

    if raw.get("mode") == "latest_completed_month":
        today = date.today()
        first_of_current_month = date(today.year, today.month, 1)
        last_of_previous_month = date.fromordinal(first_of_current_month.toordinal() - 1)
        return {
            "start_date": date(
                last_of_previous_month.year,
                last_of_previous_month.month,
                1,
            ).isoformat(),
            "end_date": last_of_previous_month.isoformat(),
        }

    if raw.get("mode") == "latest_completed_week":
        return weekly_date_range(
            week_ending_weekday=int(raw.get("week_ending_weekday", 5))
        )

    if "start_date" not in raw or "end_date" not in raw:
        raise ConfigError(
            f"Report {report.get('name', '<unnamed>')} date range needs start_date/end_date or a supported mode."
        )
    return raw


def scorecard_date(config: dict[str, Any], report: dict[str, Any]) -> str:
    raw = date_range_config(config, report)
    if raw.get("scorecard_date"):
        return raw["scorecard_date"]
    start = datetime.fromisoformat(raw["start_date"]).date()
    if report.get("date_grain") == "month":
        return date(start.year, start.month, 1).isoformat()
    return start.isoformat()


def timestamp_range(config: dict[str, Any], report: dict[str, Any]) -> tuple[str, str]:
    raw = date_range_config(config, report)
    start = datetime.combine(
        datetime.fromisoformat(raw["start_date"]).date(),
        time.min,
    )
    end = datetime.combine(
        datetime.fromisoformat(raw["end_date"]).date(),
        time.max.replace(microsecond=0),
    )
    return f"{start.isoformat()}Z", f"{end.isoformat()}Z"


def report_date_bounds(config: dict[str, Any], report: dict[str, Any]) -> tuple[date, date]:
    raw = date_range_config(config, report)
    return (
        datetime.fromisoformat(raw["start_date"]).date(),
        datetime.fromisoformat(raw["end_date"]).date(),
    )


def hubspot_get(token: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = f"?{urlencode(params, doseq=True)}" if params else ""
    request = Request(
        f"{API_BASE}{path}{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def hubspot_post(
    token: str,
    path: str,
    payload: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{API_BASE}{path}{query}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def hubspot_events_get(
    token: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = f"?{urlencode(params, doseq=True)}" if params else ""
    request = Request(
        f"{API_BASE}/email/public/v1/events{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def api_error_note(error: HTTPError | URLError) -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        return f"HubSpot API error {error.code}: {body or error.reason}"
    return f"HubSpot connection error: {error.reason}"


def histogram_buckets(response: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("results", "histogram", "data", "intervals"):
        value = response.get(key)
        if isinstance(value, list):
            return value
    if "aggregations" in response:
        return [response]
    return []


def aggregation_value(bucket: dict[str, Any], group: str, key: str) -> int | float | None:
    aggregations = bucket.get("aggregations", {})
    values = aggregations.get(group, {})
    if key in values:
        return values[key]
    lower_values = {str(item_key).lower(): value for item_key, value in values.items()}
    return lower_values.get(key.lower())


def values_from_histogram(
    response: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, int | float]:
    histogram = report.get("histogram", {})
    values: dict[str, int | float] = {}

    for bucket in histogram_buckets(response):
        for counter_key, column in histogram.get("counter_map", {}).items():
            value = aggregation_value(bucket, "counters", counter_key)
            if value is not None:
                values[column] = values.get(column, 0) + value

        # Ratios are collected for visibility but formula-owned columns are filtered
        # before Google Sheet writes.
        for ratio_key, column in histogram.get("ratio_map", {}).items():
            value = aggregation_value(bucket, "ratios", ratio_key)
            if value is not None:
                values[column] = value

    return values


def fetch_list_size(token: str, list_id: str) -> int:
    response = hubspot_get(token, f"/crm/v3/lists/{list_id}")
    hubspot_list = response.get("list", response)
    if "size" not in hubspot_list:
        raise ConfigError(f"HubSpot list {list_id} response did not include size.")
    return int(hubspot_list["size"])


def paged_hubspot_get(
    token: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    results = []
    request_params = dict(params or {})
    while True:
        response = hubspot_get(token, path, request_params)
        results.extend(response.get("results", []))
        after = response.get("paging", {}).get("next", {}).get("after")
        if not after:
            return results
        request_params["after"] = after


def content_folders(token: str) -> list[dict[str, Any]]:
    folders = []
    offset = 0
    while True:
        response = hubspot_get(
            token,
            "/content/api/v2/folders",
            {
                "limit": 100,
                "offset": offset,
            },
        )
        folders.extend(response.get("objects", []))
        next_offset = response.get("offset")
        if not next_offset:
            return folders
        offset = next_offset


def folder_name_for_date(folder_config: dict[str, Any], target_date: date) -> str:
    template = folder_config.get("folder_name_template")
    if not template:
        raise ConfigError("HubSpot email_folder config needs folder_id or folder_name_template.")
    return template.format(
        month_name=target_date.strftime("%B"),
        month=target_date.month,
        year=target_date.year,
    )


def resolve_folder_id(
    token: str,
    folder_config: dict[str, Any],
    target_date: date,
) -> str:
    if folder_config.get("folder_name_template"):
        target_name = folder_name_for_date(folder_config, target_date)
        matches = [
            folder
            for folder in content_folders(token)
            if str(folder.get("name", "")).lower() == target_name.lower()
            or str(folder.get("label", "")).lower() == target_name.lower()
        ]
        if not matches:
            raise ConfigError(f"Could not find HubSpot email folder named {target_name}.")
        if len(matches) > 1:
            ids = ", ".join(str(item.get("id")) for item in matches)
            raise ConfigError(f"Found multiple HubSpot email folders named {target_name}: {ids}.")
        return str(matches[0]["id"])

    folder_id = folder_config.get("folder_id")
    if not folder_id:
        raise ConfigError("HubSpot email_folder config needs folder_id or folder_name_template.")
    return str(folder_id)


def month_starts_between(start_date: date, end_date: date) -> list[date]:
    current = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    months = []
    while current <= end_month:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def resolve_folder_ids(
    token: str,
    folder_config: dict[str, Any],
    start_date: date,
    end_date: date,
) -> list[str]:
    if folder_config.get("folder_name_template"):
        return [
            resolve_folder_id(token, folder_config, month_start)
            for month_start in month_starts_between(start_date, end_date)
        ]
    return [resolve_folder_id(token, folder_config, end_date)]


def email_name_date_matches_report_range(
    email_name: str,
    start_date: date,
    end_date: date,
) -> bool:
    matches = re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", email_name)
    if not matches:
        return True

    for month, day, year in matches:
        parsed_year = int(year)
        if parsed_year < 100:
            parsed_year += 2000
        parsed_date = date(parsed_year, int(month), int(day))
        if start_date <= parsed_date <= end_date:
            return True
    return False


def is_included_folder_email(
    email: dict[str, Any],
    folder_config: dict[str, Any],
    start_date: date,
    end_date: date,
) -> bool:
    name = email.get("name") or ""
    if folder_config.get("only_sent", True) and email.get("state") not in SENT_EMAIL_STATES:
        return False
    for excluded in folder_config.get("exclude_name_contains", []):
        if excluded.lower() in name.lower():
            return False
    if folder_config.get("date_must_match_report_range", True):
        return email_name_date_matches_report_range(name, start_date, end_date)
    return True


def fetch_folder_emails(
    token: str,
    folder_config: dict[str, Any],
    start_date: date,
    end_date: date,
) -> tuple[list[str], list[dict[str, Any]]]:
    folder_ids = resolve_folder_ids(token, folder_config, start_date, end_date)

    emails = []
    seen_email_ids = set()
    for folder_id in folder_ids:
        for email in paged_hubspot_get(
            token,
            "/marketing/emails/2026-03",
            {
                "limit": 100,
                "folderId": folder_id,
            },
        ):
            email_id = email.get("id")
            if email_id in seen_email_ids:
                continue
            seen_email_ids.add(email_id)
            emails.append(email)

    return (
        folder_ids,
        [
            email
            for email in emails
            if is_included_folder_email(email, folder_config, start_date, end_date)
        ],
    )


def values_from_email_ids_histogram(
    token: str,
    config: dict[str, Any],
    report: dict[str, Any],
    email_ids: list[str],
) -> dict[str, int | float]:
    if not email_ids:
        return {}

    histogram = report.get("histogram", {})
    endpoint = histogram.get("endpoint")
    if not endpoint:
        raise ConfigError(f"Report {report['name']} needs histogram.endpoint.")

    start_timestamp, end_timestamp = timestamp_range(config, report)
    response = hubspot_get(
        token,
        endpoint,
        {
            "interval": histogram.get("interval", "MONTH"),
            "startTimestamp": start_timestamp,
            "endTimestamp": end_timestamp,
            "emailIds": email_ids,
        },
    )

    values: dict[str, int | float] = {}
    for bucket in histogram_buckets(response):
        for counter_key, column in report.get("email_folder", {}).get("counter_map", {}).items():
            value = aggregation_value(bucket, "counters", counter_key)
            if value is not None:
                values[column] = values.get(column, 0) + value
    return values


def email_campaign_ids(email: dict[str, Any]) -> list[str]:
    campaign_ids = []
    primary_id = email.get("primaryEmailCampaignId")
    if primary_id:
        campaign_ids.append(str(primary_id))
    campaign_ids.extend(str(item) for item in email.get("allEmailCampaignIds", []))
    return list(dict.fromkeys(campaign_ids))


def count_total_events(
    token: str,
    campaign_id: str,
    event_type: str,
) -> int:
    params: dict[str, Any] = {
        "limit": 1000,
        "campaignId": campaign_id,
        "eventType": event_type,
    }
    total = 0

    while True:
        response = hubspot_events_get(token, params)
        for event in response.get("events", []):
            if event.get("filteredEvent") is False:
                total += 1

        if not response.get("hasMore"):
            return total
        params["offset"] = response.get("offset")


def values_from_email_events(
    token: str,
    report: dict[str, Any],
    emails: list[dict[str, Any]],
) -> dict[str, int]:
    values: dict[str, int] = {}
    counted_campaign_events: set[tuple[str, str]] = set()

    for email in emails:
        for campaign_id in email_campaign_ids(email):
            for event_type, column in report.get("email_folder", {}).get("event_map", {}).items():
                key = (campaign_id, event_type)
                if key in counted_campaign_events:
                    continue
                counted_campaign_events.add(key)
                values[column] = values.get(column, 0) + count_total_events(
                    token,
                    campaign_id,
                    event_type,
                )

    return values


def fetch_histogram_record(
    token: str,
    config: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    histogram = report.get("histogram", {})
    endpoint = histogram.get("endpoint")
    if not endpoint:
        raise ConfigError(f"Report {report['name']} needs histogram.endpoint.")

    start_timestamp, end_timestamp = timestamp_range(config, report)
    response = hubspot_get(
        token,
        endpoint,
        {
            "interval": histogram.get("interval", "MONTH"),
            "startTimestamp": start_timestamp,
            "endTimestamp": end_timestamp,
        },
    )

    return {
        "source": SOURCE_NAME,
        "report": report["name"],
        "sheet": report["sheet"],
        "date_column": report["date_column"],
        "date": scorecard_date(config, report),
        "values": values_from_histogram(response, report),
    }


def fetch_email_metrics_record(
    token: str,
    config: dict[str, Any],
    report: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    start_date, end_date = report_date_bounds(config, report)
    values: dict[str, int | float] = {}
    notes = []

    subscriber_config = report.get("subscriber_list")
    if subscriber_config:
        list_id = str(subscriber_config["list_id"])
        column = subscriber_config.get("scorecard_column", "Email Subscribers")
        values[column] = fetch_list_size(token, list_id)
        notes.append(f"Mapped {column} from HubSpot list {list_id}.")

    folder_config = report.get("email_folder")
    if folder_config:
        folder_ids, emails = fetch_folder_emails(token, folder_config, start_date, end_date)
        email_ids = [str(email["id"]) for email in emails if email.get("id")]
        values.update(values_from_email_ids_histogram(token, config, report, email_ids))
        values.update(values_from_email_events(token, report, emails))
        names = ", ".join(email.get("name", "<unnamed>") for email in emails)
        notes.append(
            f"Mapped email metrics from {len(email_ids)} sent email(s) in folder(s) {', '.join(folder_ids)}: {names}."
        )
    else:
        histogram_record = fetch_histogram_record(token, config, report)
        values.update(histogram_record["values"])

    return (
        {
            "source": SOURCE_NAME,
            "report": report["name"],
            "sheet": report["sheet"],
            "date_column": report["date_column"],
            "date": scorecard_date(config, report),
            "values": values,
        },
        notes,
    )


def _fetch(config_path: str | Path | None = None, cadence: str = "monthly") -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"HubSpot {cadence} implementation is scaffolded, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure the private app token file.",
            ],
        )

    try:
        token = load_token(config)
        account = hubspot_get(token, "/account-info/v3/details")
        notes = [
            f"Loaded HubSpot config from {loaded_path}.",
            f"Authenticated to HubSpot portal {account.get('portalId', '<unknown>')}.",
        ]
        records = []
        for report in config.get("reports", []):
            if not report.get("enabled", True):
                continue
            record, report_notes = fetch_email_metrics_record(token, config, report)
            records.append(record)
            notes.extend(report_notes)
            notes.append(
                f"Fetched report {report['name']} for scorecard date {record['date']} with {len(record['values'])} mapped values."
            )
        return SourceResult(
            source=SOURCE_NAME,
            implemented=bool(records),
            records=records,
            notes=notes,
        )
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def fetch_monthly(config_path: str | Path | None = None) -> SourceResult:
    return _fetch(config_path, "monthly")


def fetch_weekly(config_path: str | Path | None = None) -> SourceResult:
    return _fetch(config_path, "weekly")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch HubSpot scorecard source data.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to HubSpot source config. Defaults to config/sources/monthly/hubspot.json.",
    )
    parser.add_argument("--weekly", action="store_true", help="Fetch weekly records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = fetch_weekly(args.config) if args.weekly else fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
