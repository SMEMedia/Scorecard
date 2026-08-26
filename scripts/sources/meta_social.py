from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
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


SOURCE_NAME = "Meta Social APIs"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "meta.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "meta.json"


class ConfigError(ValueError):
    pass


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_META_SOCIAL_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def access_token(config: dict[str, Any], item_config: dict[str, Any]) -> str:
    secrets_file = item_config.get("secrets_file") or config.get("secrets_file")
    if secrets_file:
        secrets_path = Path(secrets_file)
        if not secrets_path.exists():
            raise ConfigError(f"Meta secrets file does not exist: {secrets_path}")
        secrets = tomllib.loads(secrets_path.read_text(encoding="utf-8-sig"))
        section = item_config.get("token_section")
        key = item_config.get("token_key")
        token = (secrets.get(section, {}) if section else {}).get(key) if key else None
        if not token:
            raise ConfigError(
                f"Meta secrets file is missing {section}.{key}."
            )
        return str(token).strip()

    token_file = Path(config.get("access_token_file", ""))
    if not token_file.exists():
        raise ConfigError(f"Meta access token file does not exist: {token_file}")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ConfigError(f"Meta access token file is empty: {token_file}")
    return token


def date_range_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("default_date_range")
    if not raw:
        raise ConfigError("Meta config needs default_date_range.")

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


def graph_get(
    config: dict[str, Any],
    item_config: dict[str, Any],
    object_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    api_base = str(
        item_config.get("api_base_url", config.get("api_base_url", "https://graph.facebook.com"))
    ).rstrip("/")
    api_version = str(
        item_config.get("api_version", config.get("api_version", "v21.0"))
    ).strip("/")
    query_params = {key: value for key, value in params.items() if value not in (None, "")}
    query_params["access_token"] = access_token(config, item_config)
    url = f"{api_base}/{api_version}/{object_id}?{urlencode(query_params)}"
    request = Request(url, method="GET")
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def api_error_note(error: HTTPError | URLError) -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        return f"Meta API error {error.code}: {body or error.reason}"
    return f"Meta connection error: {error.reason}"


def fetch_current_field(
    config: dict[str, Any],
    item_config: dict[str, Any],
    id_key: str,
    field_name: str,
) -> int | float | None:
    object_id = item_config.get(id_key)
    if not object_id:
        raise ConfigError(f"Meta config missing {id_key}.")
    response = graph_get(config, item_config, str(object_id), {"fields": field_name})
    value = response.get(field_name)
    if value is None:
        return None
    return int(value)


def fetch_monthly(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Meta Social API framework is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure tokens/accounts.",
            ],
        )

    notes = [f"Loaded Meta Social config from {loaded_path}."]
    values: dict[str, int | float] = {}

    for section_name, id_key, field_name in [
        ("facebook_page", "page_id", "followers_count"),
        ("instagram_business", "ig_user_id", "followers_count"),
    ]:
        item_config = config.get(section_name, {})
        if not item_config.get("enabled", False):
            notes.append(f"{section_name} is disabled in config.")
            continue
        if item_config.get("mode") != "current_snapshot":
            notes.append(
                f"{section_name} skipped: only current_snapshot mode is scaffolded; month-end history still needs a native insights mapping."
            )
            continue
        try:
            value = fetch_current_field(config, item_config, id_key, field_name)
        except ConfigError as error:
            notes.append(f"{section_name} failed: {error}")
            continue
        except (HTTPError, URLError) as error:
            notes.append(f"{section_name} failed: {api_error_note(error)}")
            continue
        if value is not None:
            values[item_config["scorecard_column"]] = value

    records = []
    if values:
        records.append(
            {
                "source": SOURCE_NAME,
                "report": "native_meta_followers",
                "sheet": config["sheet"],
                "date_column": config["date_column"],
                "date": scorecard_date(config),
                "values": values,
            }
        )

    return SourceResult(
        source=SOURCE_NAME,
        implemented=bool(records),
        records=records,
        notes=notes,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch monthly Meta social scorecard data.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to Meta social source config. Defaults to config/sources/monthly/meta.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
