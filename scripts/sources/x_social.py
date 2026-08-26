from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from .base import SourceResult
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult


SOURCE_NAME = "X API"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "x.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "x.json"


class ConfigError(ValueError):
    pass


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_X_SOCIAL_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def bearer_token(config: dict[str, Any]) -> str:
    token_file = Path(config.get("bearer_token_file", ""))
    if not token_file.exists():
        raise ConfigError(f"X bearer token file does not exist: {token_file}")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ConfigError(f"X bearer token file is empty: {token_file}")
    return token


def date_range_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("default_date_range")
    if not raw:
        raise ConfigError("X config needs default_date_range.")

    if raw.get("mode") == "latest_completed_month":
        today = date.today()
        first_of_current_month = date(today.year, today.month, 1)
        last_of_previous_month = date.fromordinal(first_of_current_month.toordinal() - 1)
        return {
            "start_date": date(last_of_previous_month.year, last_of_previous_month.month, 1).isoformat(),
            "end_date": last_of_previous_month.isoformat(),
        }

    if "start_date" not in raw or "end_date" not in raw:
        raise ConfigError("Date range needs start_date/end_date or a supported mode.")
    return raw


def scorecard_date(config: dict[str, Any]) -> str:
    raw = date_range_config(config)
    start = datetime.fromisoformat(raw["start_date"]).date()
    return date(start.year, start.month, 1).isoformat()


def x_get(config: dict[str, Any], path: str, params: dict[str, Any]) -> dict[str, Any]:
    api_base = str(config.get("api_base_url", "https://api.x.com")).rstrip("/")
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    request = Request(
        f"{api_base}{path}?{query}",
        headers={"Authorization": f"Bearer {bearer_token(config)}"},
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def api_error_note(error: HTTPError | URLError) -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        return f"X API error {error.code}: {body or error.reason}"
    return f"X connection error: {error.reason}"


def fetch_monthly(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"X API framework is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure the bearer token/account.",
            ],
        )

    notes = [f"Loaded X config from {loaded_path}."]
    account = config.get("account", {})
    if not account.get("enabled", False):
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=notes + ["X account is disabled in config."])
    if account.get("mode") != "current_snapshot":
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=notes + ["X account skipped: only current_snapshot mode is scaffolded; month-end history requires a snapshot or another historical source."],
        )

    try:
        username = account.get("username")
        if not username:
            raise ConfigError("X config missing account.username.")
        response = x_get(
            config,
            f"/2/users/by/username/{username}",
            {"user.fields": "public_metrics"},
        )
        followers = int(response.get("data", {}).get("public_metrics", {}).get("followers_count"))
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=notes + [str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=notes + [api_error_note(error)])
    except (TypeError, ValueError):
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=notes + ["X API response did not include data.public_metrics.followers_count."],
        )

    return SourceResult(
        source=SOURCE_NAME,
        implemented=True,
        records=[
            {
                "source": SOURCE_NAME,
                "report": "native_x_followers",
                "sheet": config["sheet"],
                "date_column": config["date_column"],
                "date": scorecard_date(config),
                "values": {
                    account["scorecard_column"]: followers,
                },
            }
        ],
        notes=notes,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch monthly X social scorecard data.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to X social source config. Defaults to config/sources/monthly/x.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
