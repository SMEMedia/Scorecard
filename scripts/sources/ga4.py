from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from google.api_core.exceptions import GoogleAPIError
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Filter, FilterExpression, FilterExpressionList, Metric, RunReportRequest
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account

try:
    from .base import SourceResult
    from .weekly_utils import weekly_date_range
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult
    from sources.weekly_utils import weekly_date_range


SOURCE_NAME = "GA4"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "ga4.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "ga4.json"
READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


class ConfigError(ValueError):
    pass


def _load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_GA4_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def _get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _service_account_file(config: dict[str, Any]) -> str:
    if config.get("service_account_file"):
        return config["service_account_file"]
    env_name = config.get("service_account_file_env")
    if env_name:
        return _get_required_env(env_name)
    raise ConfigError("GA4 config needs service_account_file or service_account_file_env.")


def _oauth_client_secret_file(config: dict[str, Any]) -> str:
    oauth = config.get("oauth", {})
    if oauth.get("client_secret_file"):
        path = oauth["client_secret_file"]
        if not Path(path).exists():
            raise ConfigError(f"OAuth client secret file does not exist: {path}")
        return path
    env_name = oauth.get("client_secret_file_env")
    if env_name:
        path = _get_required_env(env_name)
        if not Path(path).exists():
            raise ConfigError(f"OAuth client secret file does not exist: {path}")
        return path
    raise ConfigError("OAuth config needs oauth.client_secret_file or oauth.client_secret_file_env.")


def _oauth_token_file(config: dict[str, Any]) -> Path:
    oauth = config.get("oauth", {})
    token_file = oauth.get("token_file")
    if not token_file:
        token_file = str(PROJECT_ROOT / "config" / "state" / "ga4_oauth_token.json")
    return Path(token_file)


def _property_id(report: dict[str, Any]) -> str:
    if report.get("property_id"):
        return str(report["property_id"])
    env_name = report.get("property_id_env")
    if env_name:
        return _get_required_env(env_name)
    raise ConfigError(f"Report {report.get('name', '<unnamed>')} needs property_id or property_id_env.")


def _date_range(config: dict[str, Any], report: dict[str, Any]) -> DateRange:
    raw = _date_range_config(config, report)
    return DateRange(start_date=raw["start_date"], end_date=raw["end_date"])


def _date_range_config(config: dict[str, Any], report: dict[str, Any]) -> dict[str, str]:
    raw = report.get("date_range") or config.get("default_date_range")
    if not raw:
        raise ConfigError(f"Report {report.get('name', '<unnamed>')} needs a date range.")

    if raw.get("mode") == "current_month_to_date":
        today = date.today()
        return {
            "start_date": date(today.year, today.month, 1).isoformat(),
            "end_date": today.isoformat(),
        }

    if raw.get("mode") == "latest_completed_month":
        today = date.today()
        first_of_current_month = date(today.year, today.month, 1)
        last_of_previous_month = first_of_current_month.replace(day=1)
        last_of_previous_month = date.fromordinal(last_of_previous_month.toordinal() - 1)
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


def _scorecard_date(config: dict[str, Any], report: dict[str, Any]) -> str:
    raw = _date_range_config(config, report)
    if raw.get("scorecard_date"):
        return raw["scorecard_date"]
    start = datetime.fromisoformat(raw["start_date"]).date()
    if report.get("date_grain") == "month":
        return date(start.year, start.month, 1).isoformat()
    return start.isoformat()


def _make_service_account_client(config: dict[str, Any]) -> BetaAnalyticsDataClient:
    credentials = service_account.Credentials.from_service_account_file(
        _service_account_file(config),
        scopes=[READONLY_SCOPE],
    )
    return BetaAnalyticsDataClient(credentials=credentials)


def _make_oauth_client(config: dict[str, Any]) -> BetaAnalyticsDataClient:
    token_file = _oauth_token_file(config)
    credentials = None

    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), [READONLY_SCOPE])

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                _oauth_client_secret_file(config),
                scopes=[READONLY_SCOPE],
            )
            credentials = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(token_file, "w", encoding="utf-8") as handle:
            handle.write(credentials.to_json())

    return BetaAnalyticsDataClient(credentials=credentials)


def _make_client(config: dict[str, Any]) -> BetaAnalyticsDataClient:
    auth_mode = config.get("auth_mode", "service_account")
    if auth_mode == "oauth":
        return _make_oauth_client(config)
    if auth_mode == "service_account":
        return _make_service_account_client(config)
    raise ConfigError(f"Unsupported GA4 auth_mode: {auth_mode}")


def _metric_value(value: str) -> int | float:
    if "." in value:
        return float(value)
    return int(value)


def _run_report(
    client: BetaAnalyticsDataClient,
    config: dict[str, Any],
    report: dict[str, Any],
) -> Any:
    request = RunReportRequest(
        property=f"properties/{_property_id(report)}",
        date_ranges=[_date_range(config, report)],
        dimensions=[Dimension(name=name) for name in report.get("dimensions", [])],
        metrics=[Metric(name=item["api_name"]) for item in report.get("metrics", [])],
        dimension_filter=_dimension_filter(report),
    )
    return client.run_report(request)


def _dimension_filter(report: dict[str, Any]) -> FilterExpression | None:
    raw_filter = report.get("dimension_filter")
    if not raw_filter:
        return None
    return _build_filter_expression(raw_filter)


def _build_filter_expression(raw_filter: dict[str, Any]) -> FilterExpression:
    if raw_filter.get("type") == "and_group":
        return FilterExpression(
            and_group=FilterExpressionList(
                expressions=[
                    _build_filter_expression(item)
                    for item in raw_filter.get("expressions", [])
                ]
            )
        )
    if raw_filter.get("type") == "or_group":
        return FilterExpression(
            or_group=FilterExpressionList(
                expressions=[
                    _build_filter_expression(item)
                    for item in raw_filter.get("expressions", [])
                ]
            )
        )
    if raw_filter.get("type") == "in_list":
        return FilterExpression(
            filter=Filter(
                field_name=raw_filter["field_name"],
                in_list_filter=Filter.InListFilter(
                    values=raw_filter["values"],
                    case_sensitive=raw_filter.get("case_sensitive", True),
                ),
            )
        )
    if raw_filter.get("type") == "contains":
        return FilterExpression(
            filter=Filter(
                field_name=raw_filter["field_name"],
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.CONTAINS,
                    value=raw_filter["value"],
                    case_sensitive=raw_filter.get("case_sensitive", True),
                ),
            )
        )
    if raw_filter.get("type") == "exact":
        return FilterExpression(
            filter=Filter(
                field_name=raw_filter["field_name"],
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.EXACT,
                    value=raw_filter["value"],
                    case_sensitive=raw_filter.get("case_sensitive", True),
                ),
            )
        )
    raise ConfigError(f"Unsupported GA4 dimension_filter type: {raw_filter.get('type')}")


def _safe_formula_eval(formula: str, values: dict[str, int | float]) -> int | float | None:
    safe_names = {f"v{idx}": key for idx, key in enumerate(sorted(values, key=len, reverse=True))}
    rewritten_formula = formula
    eval_values = {}
    for safe_name, label in safe_names.items():
        rewritten_formula = rewritten_formula.replace(label, safe_name)
        eval_values[safe_name] = values[label]

    tree = ast.parse(rewritten_formula, mode="eval")
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Load,
        ast.Name,
        ast.Constant,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"Unsupported derived metric formula: {formula}")

    try:
        result = eval(rewritten_formula, {"__builtins__": {}}, eval_values)
    except ZeroDivisionError:
        return None
    return result


def _apply_derived_metrics(report: dict[str, Any], values: dict[str, int | float]) -> None:
    for derived in report.get("derived_metrics", []):
        values[derived["name"]] = _safe_formula_eval(derived["formula"], values)


def _api_error_notes(error: GoogleAPIError) -> list[str]:
    notes = [str(error).split(" [reason:")[0]]
    for detail in getattr(error, "details", []) or []:
        metadata = getattr(detail, "metadata", {}) or {}
        activation_url = metadata.get("activationUrl")
        if activation_url:
            notes.append(f"Enable the API here: {activation_url}")
    return notes


def _scalar_record(
    config: dict[str, Any],
    report: dict[str, Any],
    response: Any,
) -> dict[str, Any]:
    values: dict[str, int | float] = {}
    if response.rows:
        row = response.rows[0]
        for idx, metric in enumerate(report.get("metrics", [])):
            values[metric["scorecard_column"]] = _metric_value(row.metric_values[idx].value)

    _apply_derived_metrics(report, values)
    return {
        "source": SOURCE_NAME,
        "report": report["name"],
        "sheet": report["sheet"],
        "date_column": report["date_column"],
        "date": _scorecard_date(config, report),
        "values": values,
    }


def _dimension_record(
    config: dict[str, Any],
    report: dict[str, Any],
    response: Any,
) -> dict[str, Any]:
    aggregate_metrics = {
        item["api_name"]: item["scorecard_column"]
        for item in report.get("aggregate_metrics", [])
    }
    values: dict[str, int | float] = {
        scorecard_column: 0
        for scorecard_column in aggregate_metrics.values()
    }
    value_map = {key.lower(): value for key, value in report.get("dimension_value_map", {}).items()}

    for row in response.rows:
        dimension_value = row.dimension_values[0].value.lower()
        scorecard_column = value_map.get(dimension_value)
        if scorecard_column:
            values[scorecard_column] = values.get(scorecard_column, 0) + _metric_value(
                row.metric_values[0].value
            )

        for idx, metric in enumerate(report.get("metrics", [])):
            aggregate_column = aggregate_metrics.get(metric["api_name"])
            if not aggregate_column:
                continue
            values[aggregate_column] = values.get(aggregate_column, 0) + _metric_value(
                row.metric_values[idx].value
            )

    return {
        "source": SOURCE_NAME,
        "report": report["name"],
        "sheet": report["sheet"],
        "date_column": report["date_column"],
        "date": _scorecard_date(config, report),
        "values": values,
    }


def _apply_engagement_percentages(records: list[dict[str, Any]]) -> None:
    records_by_sheet_date: dict[tuple[str, str, str], dict[str, int | float]] = {}
    for record in records:
        key = (record["sheet"], record["date_column"], record["date"])
        records_by_sheet_date.setdefault(key, {}).update(record.get("values", {}))

    for record in records:
        if record.get("sheet") != "SME Media Engagement Metrics":
            continue

        key = (record["sheet"], record["date_column"], record["date"])
        combined_values = records_by_sheet_date.get(key, {})
        total_users = combined_values.get("AM.org Total Users (#)")
        if not total_users:
            continue

        values = record.setdefault("values", {})
        engaged_users = combined_values.get("Engaged Total Users (user_engagement)")
        scroll_users = combined_values.get("Scroll Total Users (90% page depth)")
        if engaged_users is not None:
            values["Engaged Total Users %"] = engaged_users / total_users
        if scroll_users is not None:
            values["% Scroll Users from Total"] = scroll_users / total_users


def _fetch(config_path: str | Path | None = None, cadence: str = "monthly") -> SourceResult:
    config, loaded_path, used_example = _load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"GA4 {cadence} implementation is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and fill in service account and property IDs.",
            ],
        )

    try:
        client = _make_client(config)
        records = []
        notes = [f"Loaded GA4 config from {loaded_path}."]
        for report in config.get("reports", []):
            if not report.get("enabled", True):
                continue
            try:
                response = _run_report(client, config, report)
            except GoogleAPIError as error:
                report_name = report.get("name", "<unnamed>")
                property_hint = report.get("property_id") or report.get("property_id_env")
                notes.append(
                    f"Report {report_name} failed for property {property_hint}: {_api_error_notes(error)[0]}"
                )
                continue
            if report.get("dimensions"):
                records.append(_dimension_record(config, report, response))
            else:
                records.append(_scalar_record(config, report, response))

        _apply_engagement_percentages(records)
        return SourceResult(
            source=SOURCE_NAME,
            implemented=bool(records),
            records=records,
            notes=notes,
        )
    except ConfigError as error:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[str(error)],
        )
    except GoogleAPIError as error:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=_api_error_notes(error),
        )


def fetch_monthly(config_path: str | Path | None = None) -> SourceResult:
    return _fetch(config_path, "monthly")


def fetch_weekly(config_path: str | Path | None = None) -> SourceResult:
    return _fetch(config_path, "weekly")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch GA4 scorecard source data.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to GA4 source config. Defaults to config/sources/monthly/ga4.json.",
    )
    parser.add_argument("--weekly", action="store_true", help="Fetch weekly records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = fetch_weekly(args.config) if args.weekly else fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
