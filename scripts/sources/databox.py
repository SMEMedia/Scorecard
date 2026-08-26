from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from .base import SourceResult
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult


SOURCE_NAME = "DataBox"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "optional" / "databox.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "databox.json"


class ConfigError(ValueError):
    pass


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_DATABOX_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def api_key(config: dict[str, Any]) -> str:
    key_file = Path(config.get("api_key_file", ""))
    if not key_file.exists():
        raise ConfigError(f"Databox API key file does not exist: {key_file}")
    key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise ConfigError(f"Databox API key file is empty: {key_file}")
    return key


def api_base_url(config: dict[str, Any]) -> str:
    return str(config.get("api_base_url", "https://api.databox.com")).rstrip("/")


def databox_get(config: dict[str, Any], path: str) -> dict[str, Any]:
    request = Request(
        f"{api_base_url(config)}{path}",
        headers={"x-api-key": api_key(config)},
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def date_range_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("default_date_range")
    if not raw:
        raise ConfigError("Databox config needs default_date_range.")

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

    if "start_date" not in raw or "end_date" not in raw:
        raise ConfigError("Date range needs start_date/end_date or a supported mode.")
    return raw


def scorecard_date(config: dict[str, Any]) -> str:
    raw = date_range_config(config)
    start = datetime.fromisoformat(raw["start_date"]).date()
    return date(start.year, start.month, 1).isoformat()


def api_error_note(error: HTTPError | URLError) -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        return f"Databox API error {error.code}: {body or error.reason}"
    return f"Databox connection error: {error.reason}"


def summarize_collection(payload: dict[str, Any], key: str, fields: list[str]) -> list[dict[str, Any]]:
    rows = []
    for item in payload.get(key, []) or []:
        rows.append({field: item.get(field) for field in fields if field in item})
    return rows


def discover(
    config_path: str | Path | None = None,
    include_datasets: bool = False,
) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Databox discovery is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and fill in the API key path.",
            ],
        )

    try:
        notes = [f"Loaded Databox config from {loaded_path}."]
        validate = databox_get(config, "/v1/auth/validate-key")
        notes.append(f"API key validation status: {validate.get('status', '<unknown>')}.")

        accounts_payload = databox_get(config, "/v1/accounts")
        accounts = summarize_collection(
            accounts_payload,
            "accounts",
            ["id", "name", "title", "timezone"],
        )
        notes.append(f"Found {len(accounts)} accessible Databox account(s).")

        discovery_config = config.get("discovery", {})
        configured_dataset_source_ids = {
            int(item) for item in discovery_config.get("dataset_source_ids", [])
        }
        include_datasets = include_datasets or bool(discovery_config.get("include_datasets", False))
        max_dataset_sources = int(discovery_config.get("max_dataset_sources", 10))
        dataset_source_count = 0

        discovery_records = {"accounts": accounts, "data_sources": []}
        for account in accounts:
            account_id = account.get("id")
            if account_id is None:
                continue
            data_sources_payload = databox_get(
                config,
                f"/v1/accounts/{account_id}/data-sources",
            )
            data_sources = summarize_collection(
                data_sources_payload,
                "dataSources",
                ["id", "title", "name", "key", "timezone", "ingestionSupported"],
            )
            notes.append(
                f"Account {account_id} has {len(data_sources)} data source(s)."
            )
            discovery_records["data_sources"].append(
                {
                    "account_id": account_id,
                    "data_sources": data_sources,
                }
            )

            for data_source in data_sources:
                if not include_datasets:
                    continue
                data_source_id = data_source.get("id")
                if data_source_id is None:
                    continue
                if configured_dataset_source_ids and data_source_id not in configured_dataset_source_ids:
                    continue
                if not configured_dataset_source_ids and dataset_source_count >= max_dataset_sources:
                    continue
                try:
                    datasets_payload = databox_get(
                        config,
                        f"/v1/data-sources/{data_source_id}/datasets",
                    )
                except (HTTPError, URLError) as error:
                    notes.append(
                        f"Data source {data_source_id} dataset listing failed: {api_error_note(error)}"
                    )
                    continue
                datasets = summarize_collection(
                    datasets_payload,
                    "datasets",
                    ["id", "title", "name", "key", "created"],
                )
                data_source["datasets"] = datasets
                dataset_source_count += 1
                notes.append(
                    f"Data source {data_source_id} has {len(datasets)} dataset(s)."
                )

        if not include_datasets:
            notes.append(
                "Dataset listing was skipped. Use --include-datasets or config.discovery.include_datasets to inspect datasets."
            )

        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=[discovery_records],
            notes=notes,
        )
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def fetch_monthly(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Databox implementation is scaffolded, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and fill in the API key path.",
            ],
        )

    try:
        api_key(config)
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])

    metric_mappings = config.get("metric_mappings", [])
    mapped_columns = ", ".join(item["scorecard_column"] for item in metric_mappings)
    return SourceResult(
        source=SOURCE_NAME,
        implemented=False,
        notes=[
            f"Loaded Databox config from {loaded_path}.",
            "Databox key is present, but monthly metric retrieval is not enabled yet.",
            "The Databox v1 public API currently exposes account/data-source/dataset discovery and ingestion endpoints; the historical existing-metric read endpoint still needs to be confirmed.",
            f"Configured Databox scorecard columns for {scorecard_date(config)}: {mapped_columns}.",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch or discover Databox scorecard data.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to Databox source config. Defaults to config/sources/optional/databox.json.",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Validate the key and list accessible Databox accounts, data sources, and datasets.",
    )
    parser.add_argument(
        "--include-datasets",
        action="store_true",
        help="Also list datasets for configured data source IDs, or for a limited number of sources.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = discover(args.config, args.include_datasets) if args.discover else fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
