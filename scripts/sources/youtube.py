from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone, time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

try:
    from .base import SourceResult
    from .weekly_utils import weekly_date_range
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult
    from sources.weekly_utils import weekly_date_range


SOURCE_NAME = "YouTube"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "youtube.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "youtube.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
ANALYTICS_API_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"


class ConfigError(ValueError):
    pass


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_YOUTUBE_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def date_range_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("default_date_range")
    if not raw:
        raise ConfigError("YouTube config needs default_date_range.")

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
        raise ConfigError("Date range needs start_date/end_date or a supported mode.")
    return raw


def scorecard_date(config: dict[str, Any], report: dict[str, Any]) -> str:
    raw = date_range_config(config)
    if raw.get("scorecard_date"):
        return raw["scorecard_date"]
    start = datetime.fromisoformat(raw["start_date"]).date()
    if report.get("date_grain") == "month":
        return date(start.year, start.month, 1).isoformat()
    return start.isoformat()


def oauth_client_secret_file(config: dict[str, Any]) -> str:
    path = Path(config.get("oauth", {}).get("client_secret_file", ""))
    if not path.exists():
        raise ConfigError(f"YouTube OAuth client secret file does not exist: {path}")
    return str(path)


def oauth_token_file(config: dict[str, Any]) -> Path:
    token_file = config.get("oauth", {}).get("token_file")
    if not token_file:
        token_file = str(PROJECT_ROOT / "config" / "state" / "youtube_oauth_token.json")
    return Path(token_file)


def make_oauth_credentials(config: dict[str, Any]) -> Credentials:
    token_file = oauth_token_file(config)
    credentials = None

    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    needs_scope_upgrade = credentials and not credentials.has_scopes(SCOPES)
    if not credentials or not credentials.valid or needs_scope_upgrade:
        if credentials and credentials.expired and credentials.refresh_token and not needs_scope_upgrade:
            try:
                credentials.refresh(GoogleAuthRequest())
            except RefreshError as error:
                token_file.unlink(missing_ok=True)
                raise ConfigError(
                    "The YouTube authorization has expired or was revoked. "
                    "An administrator must authorize YouTube again locally and replace "
                    "the youtube_oauth_token value in Streamlit Secrets. If this recurs "
                    "every seven days, use Reconnect YouTube in the Streamlit app's left "
                    "menu, then replace the token block in Streamlit Secrets."
                ) from error
        else:
            raise ConfigError(
                "YouTube authorization is missing or does not include the required scopes. "
                "Use Reconnect YouTube in the Streamlit app's left menu, then replace "
                "the token block in Streamlit Secrets."
            )
            credentials = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    return credentials


def authorize_oauth(config_path: str | Path | None = None) -> Path:
    """Run the administrator-only local browser flow and replace the saved token."""
    config, _, used_example = load_config(config_path)
    if used_example:
        raise ConfigError("Create the YouTube source config before authorizing YouTube.")
    flow = InstalledAppFlow.from_client_secrets_file(
        oauth_client_secret_file(config),
        scopes=SCOPES,
    )
    credentials = flow.run_local_server(port=0)
    token_file = oauth_token_file(config)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return token_file


def service_account_file(config: dict[str, Any]) -> str:
    path = config.get("service_account_file")
    if not path:
        raise ConfigError("YouTube service_account_file is not configured.")
    if not Path(path).exists():
        raise ConfigError(f"YouTube service account file does not exist: {path}")
    return path


def make_service_account_credentials(config: dict[str, Any]) -> service_account.Credentials:
    return service_account.Credentials.from_service_account_file(
        service_account_file(config),
        scopes=SCOPES,
    )


def make_credentials(config: dict[str, Any]) -> Any:
    auth_mode = config.get("auth_mode", "oauth")
    if auth_mode == "oauth":
        return make_oauth_credentials(config)
    if auth_mode == "service_account":
        return make_service_account_credentials(config)
    raise ConfigError(f"Unsupported YouTube auth_mode: {auth_mode}")


def authed_get_json(credentials: Credentials, url: str, params: dict[str, Any]) -> dict[str, Any]:
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())

    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    request = Request(
        f"{url}?{query}",
        headers={"Authorization": f"Bearer {credentials.token}"},
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def analytics_values(response: dict[str, Any]) -> dict[str, int | float]:
    rows = response.get("rows") or []
    if not rows:
        return {}
    headers = [item["name"] for item in response.get("columnHeaders", [])]
    return {headers[idx]: rows[0][idx] for idx in range(len(headers))}


def list_playlists(credentials: Credentials) -> list[dict[str, Any]]:
    playlists = []
    page_token = None
    while True:
        params = {
            "part": "snippet",
            "mine": "true",
            "maxResults": 50,
            "pageToken": page_token,
        }
        response = authed_get_json(credentials, f"{YOUTUBE_API_URL}/playlists", params)
        playlists.extend(response.get("items") or [])
        page_token = response.get("nextPageToken")
        if not page_token:
            return playlists


def resolve_playlist_id(credentials: Credentials, title: str) -> str:
    normalized_title = title.strip().casefold()
    playlists = list_playlists(credentials)
    for playlist in playlists:
        playlist_title = playlist.get("snippet", {}).get("title", "")
        if playlist_title.strip().casefold() == normalized_title:
            return playlist["id"]

    close_titles = [
        playlist.get("snippet", {}).get("title", "")
        for playlist in playlists
        if normalized_title in playlist.get("snippet", {}).get("title", "").casefold()
        or playlist.get("snippet", {}).get("title", "").casefold() in normalized_title
    ]
    if len(close_titles) == 1:
        for playlist in playlists:
            if playlist.get("snippet", {}).get("title", "") == close_titles[0]:
                return playlist["id"]

    available = ", ".join(
        playlist.get("snippet", {}).get("title", "<untitled>") for playlist in playlists
    )
    raise ConfigError(
        f"Could not resolve YouTube playlist/podcast title {title!r}. "
        f"Available playlists: {available or '<none>'}"
    )


def report_filters(credentials: Credentials, report: dict[str, Any]) -> str | None:
    if report.get("playlist_id"):
        return f"playlist=={report['playlist_id']}"
    if report.get("playlist_title"):
        return f"playlist=={resolve_playlist_id(credentials, report['playlist_title'])}"
    return report.get("filters")


def query_analytics(
    credentials: Credentials,
    config: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, int | float]:
    filters = report_filters(credentials, report)
    if isinstance(filters, str) and "REPLACE_WITH_" in filters:
        raise ConfigError(
            f"Report {report['name']} needs a real YouTube Analytics filter before it can run: {filters}"
        )
    raw_range = date_range_config(config)
    params = {
        "ids": report.get("ids", "channel==MINE"),
        "startDate": raw_range["start_date"],
        "endDate": raw_range["end_date"],
        "metrics": ",".join(report["metrics"]),
        "filters": filters,
    }
    return analytics_values(authed_get_json(credentials, ANALYTICS_API_URL, params))


def metric_to_scorecard_value(
    metric: str,
    value: int | float,
    transform: str | None,
) -> int | float | time:
    if transform == "minutes_to_hours":
        return float(value) / 60
    if transform == "seconds_to_excel_time":
        return float(value) / 86400
    if transform == "seconds_to_mmss_time":
        total_seconds = int(round(float(value)))
        minutes, seconds = divmod(total_seconds, 60)
        if minutes > 23:
            raise ConfigError(
                f"Cannot store {total_seconds} seconds as the scorecard's mm:ss-style time value."
            )
        return time(minutes, seconds)
    if metric == "views":
        return int(value)
    return value


def analytics_record(
    credentials: Credentials,
    config: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    values = query_analytics(credentials, config, report)
    scorecard_values = {}
    for mapping in report.get("scorecard_metrics", []):
        api_metric = mapping["api_metric"]
        if api_metric not in values:
            continue
        scorecard_values[mapping["scorecard_column"]] = metric_to_scorecard_value(
            api_metric,
            values[api_metric],
            mapping.get("transform"),
        )

    return {
        "source": SOURCE_NAME,
        "report": report["name"],
        "sheet": report["sheet"],
        "date_column": report["date_column"],
        "date": scorecard_date(config, report),
        "values": scorecard_values,
    }


def subscriber_count(credentials: Credentials, report: dict[str, Any]) -> int:
    params = {
        "part": "statistics",
        "mine": "true" if report.get("mine", True) else None,
        "id": report.get("channel_id") if not report.get("mine", True) else None,
    }
    response = authed_get_json(credentials, f"{YOUTUBE_API_URL}/channels", params)
    items = response.get("items") or []
    if not items:
        raise ConfigError("YouTube channels.list returned no channels for the authenticated user.")
    return int(items[0].get("statistics", {}).get("subscriberCount", 0))


def snapshot_file(config: dict[str, Any], report: dict[str, Any]) -> Path:
    configured = report.get("snapshot_file") or config.get("subscriber_snapshot_file")
    if configured:
        return Path(configured)
    return PROJECT_ROOT / "config" / "state" / "youtube_subscribers.json"


def load_snapshots(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"snapshots": {}}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"snapshots": {}}
    payload = json.loads(raw)
    if "snapshots" not in payload or not isinstance(payload["snapshots"], dict):
        payload["snapshots"] = {}
    return payload


def save_snapshots(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def subscriber_snapshot_value(
    credentials: Credentials,
    config: dict[str, Any],
    report: dict[str, Any],
    scorecard_month: str,
) -> tuple[int, str]:
    if not report.get("use_snapshot", True):
        return subscriber_count(credentials, report), "Read current YouTube subscriber count without snapshot storage."

    path = snapshot_file(config, report)
    payload = load_snapshots(path)
    snapshots = payload["snapshots"]
    if scorecard_month in snapshots:
        snapshot = snapshots[scorecard_month]
        return int(snapshot["value"]), (
            f"Used saved YouTube subscriber snapshot for {scorecard_month} from {path}."
        )

    value = subscriber_count(credentials, report)
    snapshots[scorecard_month] = {
        "value": value,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "YouTube Data API channels.list statistics.subscriberCount",
        "note": (
            "Captured when no saved month snapshot existed. For exact month-end values, "
            "run the automation immediately after month close or replace this value manually."
        ),
    }
    save_snapshots(path, payload)
    return value, (
        f"Created YouTube subscriber snapshot for {scorecard_month} at {path}. "
        "If this should represent a prior month-end, verify the value before writing."
    )


def subscribers_record(
    credentials: Credentials,
    config: dict[str, Any],
    report: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    record_date = scorecard_date(config, report)
    value, note = subscriber_snapshot_value(credentials, config, report, record_date)
    return {
        "source": SOURCE_NAME,
        "report": report["name"],
        "sheet": report["sheet"],
        "date_column": report["date_column"],
        "date": record_date,
        "values": {
            report["scorecard_column"]: value,
        },
    }, note


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
        if message == "Forbidden":
            message = (
                "Forbidden. Confirm the OAuth account has access to the SME Media YouTube "
                "channel and that the YouTube Analytics API and YouTube Data API v3 are "
                "enabled for the OAuth client project."
            )
        activation_urls = []
        for detail in api_error.get("details", []):
            metadata = detail.get("metadata", {})
            activation_url = metadata.get("activationUrl")
            if activation_url:
                activation_urls.append(activation_url)
        if activation_urls:
            return f"YouTube API error {error.code}: {message} Enable here: {activation_urls[0]}"
        return f"YouTube API error {error.code}: {message}"
    return f"YouTube connection error: {error.reason}"


def _fetch(config_path: str | Path | None = None, cadence: str = "monthly") -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"YouTube {cadence} implementation is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure OAuth.",
            ],
        )

    try:
        credentials = make_credentials(config)
        records = []
        auth_mode = config.get("auth_mode", "oauth")
        notes = [f"Loaded YouTube config from {loaded_path}."]
        if auth_mode == "service_account":
            notes.append(
                "Using service-account auth. Google documents that the YouTube Data API does not support service accounts for channel/user data, so this may fail with NoLinkedYouTubeAccount."
            )

        for report in config.get("reports", []):
            if not report.get("enabled", True):
                continue
            report_type = report.get("type")
            try:
                if report_type == "analytics":
                    records.append(analytics_record(credentials, config, report))
                elif report_type == "subscribers":
                    record, note = subscribers_record(credentials, config, report)
                    records.append(record)
                    notes.append(note)
                else:
                    notes.append(
                        f"Report {report.get('name', '<unnamed>')} skipped: unsupported type {report_type!r}."
                    )
            except (ConfigError, HTTPError, URLError) as error:
                report_name = report.get("name", "<unnamed>")
                if isinstance(error, (HTTPError, URLError)):
                    notes.append(f"Report {report_name} failed: {api_error_note(error)}")
                else:
                    notes.append(f"Report {report_name} failed: {error}")

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
    parser = argparse.ArgumentParser(description="Fetch YouTube scorecard source data.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YouTube source config. Defaults to config/sources/monthly/youtube.json.",
    )
    parser.add_argument("--weekly", action="store_true", help="Fetch weekly records.")
    parser.add_argument(
        "--authorize",
        action="store_true",
        help="Open a local browser to replace the saved YouTube OAuth token.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.authorize:
        token_file = authorize_oauth(args.config)
        print(f"YouTube authorization saved to {token_file}.")
        return
    result = fetch_weekly(args.config) if args.weekly else fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
