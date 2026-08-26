from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

try:
    from .base import SourceResult
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult


SOURCE_NAME = "Google Play Console + App Store"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "optional" / "google_play.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "google_play.json"
READONLY_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"
STORAGE_API_BASE = "https://storage.googleapis.com/storage/v1"
APP_STORE_API_BASE = "https://api.appstoreconnect.apple.com/v1"


class ConfigError(ValueError):
    pass


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_GOOGLE_PLAY_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def date_range_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("default_date_range")
    if not raw:
        raise ConfigError("Google Play config needs default_date_range.")

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


def scorecard_date(config: dict[str, Any], play_config: dict[str, Any]) -> str:
    raw = date_range_config(config)
    start = datetime.fromisoformat(raw["start_date"]).date()
    if play_config.get("date_grain") == "month":
        return date(start.year, start.month, 1).isoformat()
    return start.isoformat()


def year_month(config: dict[str, Any]) -> str:
    raw = date_range_config(config)
    start = datetime.fromisoformat(raw["start_date"]).date()
    return f"{start.year}{start.month:02d}"


def app_store_report_month(config: dict[str, Any]) -> str:
    raw = date_range_config(config)
    start = datetime.fromisoformat(raw["start_date"]).date()
    return f"{start.year}-{start.month:02d}"


def oauth_client_secret_file(config: dict[str, Any]) -> str:
    path = Path(config.get("oauth", {}).get("client_secret_file", ""))
    if not path.exists():
        raise ConfigError(f"Google Play OAuth client secret file does not exist: {path}")
    return str(path)


def oauth_token_file(config: dict[str, Any]) -> Path:
    token_file = config.get("oauth", {}).get("token_file")
    if not token_file:
        token_file = str(PROJECT_ROOT / "config" / "state" / "google_play_oauth_token.json")
    return Path(token_file)


def make_oauth_credentials(config: dict[str, Any]) -> Credentials:
    token_file = oauth_token_file(config)
    credentials = None

    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), [READONLY_SCOPE])

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleAuthRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                oauth_client_secret_file(config),
                scopes=[READONLY_SCOPE],
            )
            credentials = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    return credentials


def make_service_account_credentials(config: dict[str, Any]) -> service_account.Credentials:
    service_account_file = config.get("service_account_file")
    if not service_account_file:
        raise ConfigError("Google Play service_account_file is not configured.")
    path = Path(service_account_file)
    if not path.exists():
        raise ConfigError(f"Google Play service account file does not exist: {path}")
    return service_account.Credentials.from_service_account_file(
        str(path),
        scopes=[READONLY_SCOPE],
    )


def make_credentials(config: dict[str, Any]) -> Any:
    auth_mode = config.get("auth_mode", "oauth")
    if auth_mode == "oauth":
        return make_oauth_credentials(config)
    if auth_mode == "service_account":
        return make_service_account_credentials(config)
    raise ConfigError(f"Unsupported Google Play auth_mode: {auth_mode}")


def storage_get_bytes(credentials: Any, bucket_id: str, object_name: str) -> bytes:
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())

    encoded_object = quote(object_name, safe="")
    request = Request(
        f"{STORAGE_API_BASE}/b/{bucket_id}/o/{encoded_object}?alt=media",
        headers={"Authorization": f"Bearer {credentials.token}"},
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        return response.read()


def storage_list_object_names(
    credentials: Any,
    bucket_id: str,
    prefix: str,
    max_results: int = 20,
) -> list[str]:
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())

    params = urlencode({"prefix": prefix, "maxResults": str(max_results)})
    request = Request(
        f"{STORAGE_API_BASE}/b/{bucket_id}/o?{params}",
        headers={"Authorization": f"Bearer {credentials.token}"},
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [item["name"] for item in payload.get("items", [])]


def report_object_name(config: dict[str, Any], play_config: dict[str, Any]) -> str:
    bucket_id = play_config.get("bucket_id")
    package_name = play_config.get("package_name")
    missing = []
    if not bucket_id:
        missing.append("bucket_id")
    if not package_name:
        missing.append("package_name")
    if missing:
        raise ConfigError(f"Google Play config is missing: {', '.join(missing)}.")

    template = play_config.get("report_object_template")
    if not template:
        raise ConfigError("Google Play report_object_template is not configured.")
    return template.format(package_name=package_name, year_month=year_month(config))


def report_object_prefix(config: dict[str, Any], play_config: dict[str, Any]) -> str:
    package_name = play_config.get("package_name")
    if not package_name:
        raise ConfigError("Google Play config is missing: package_name.")
    return f"stats/installs/installs_{package_name}_{year_month(config)}"


def parse_installs_metric(csv_bytes: bytes, encoding: str, metric_column: str) -> int:
    text = csv_bytes.decode(encoding)
    reader = csv.DictReader(io.StringIO(text))
    total = 0
    found = False
    for row in reader:
        if metric_column not in row:
            available = ", ".join(row.keys())
            raise ConfigError(
                f"Metric column '{metric_column}' not found in Google Play CSV. Available columns: {available}"
            )
        raw_value = (row.get(metric_column) or "0").replace(",", "").strip()
        if not raw_value:
            continue
        total += int(float(raw_value))
        found = True
    if not found:
        raise ConfigError(f"No values found for Google Play metric column '{metric_column}'.")
    return total


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def app_store_key_id(app_config: dict[str, Any]) -> str:
    if app_config.get("key_id"):
        return app_config["key_id"]
    key_file = Path(app_config.get("private_key_file", ""))
    if key_file.name.startswith("ApiKey_") and key_file.suffix == ".p8":
        return key_file.stem.removeprefix("ApiKey_")
    raise ConfigError("App Store Connect key_id is not configured.")


def app_store_private_key(app_config: dict[str, Any]) -> ec.EllipticCurvePrivateKey:
    key_file = Path(app_config.get("private_key_file", ""))
    if not key_file.exists():
        raise ConfigError(f"App Store Connect private key file does not exist: {key_file}")
    key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ConfigError("App Store Connect private key must be an EC private key.")
    return key


def app_store_jwt(app_config: dict[str, Any]) -> str:
    key_type = app_config.get("key_type", "team")
    issuer_id = app_config.get("issuer_id")
    if key_type != "individual" and not issuer_id:
        raise ConfigError("App Store Connect issuer_id is not configured.")
    now = int(datetime.now(timezone.utc).timestamp())
    header = {
        "alg": "ES256",
        "kid": app_store_key_id(app_config),
        "typ": "JWT",
    }
    payload = {
        "iat": now,
        "exp": now + 20 * 60,
        "aud": "appstoreconnect-v1",
    }
    if key_type != "individual":
        payload["iss"] = issuer_id
    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}.{b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    der_signature = app_store_private_key(app_config).sign(
        signing_input.encode("ascii"),
        ec.ECDSA(hashes.SHA256()),
    )
    r, s = utils.decode_dss_signature(der_signature)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input}.{b64url(signature)}"


def app_store_sales_report_bytes(config: dict[str, Any], app_config: dict[str, Any]) -> bytes:
    missing = []
    if app_config.get("key_type", "team") != "individual" and not app_config.get("issuer_id"):
        missing.append("issuer_id")
    vendor_number = app_config.get("vendor_number")
    if not vendor_number:
        missing.append("vendor_number")
    if missing:
        raise ConfigError(f"App Store Connect config is missing: {', '.join(missing)}.")

    params = {
        "filter[frequency]": app_config.get("frequency", "MONTHLY"),
        "filter[reportDate]": app_config.get("report_date") or app_store_report_month(config),
        "filter[reportSubType]": app_config.get("report_subtype", "SUMMARY"),
        "filter[reportType]": app_config.get("report_type", "SALES"),
        "filter[vendorNumber]": vendor_number,
        "filter[version]": app_config.get("version", "1_0"),
    }
    request = Request(
        f"{APP_STORE_API_BASE}/salesReports?{urlencode(params)}",
        headers={
            "Authorization": f"Bearer {app_store_jwt(app_config)}",
            "Accept": "application/a-gzip",
        },
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        body = response.read()
    try:
        return gzip.decompress(body)
    except OSError:
        return body


def parse_app_store_units(report_bytes: bytes, app_config: dict[str, Any]) -> int:
    text = report_bytes.decode(app_config.get("encoding", "utf-8-sig"))
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    units_column = app_config.get("units_column", "Units")
    product_type_filter = set(app_config.get("product_type_identifiers", ["1", "1F", "1T"]))
    sku_filter = set(app_config.get("skus", []))
    app_apple_id_filter = set(str(item) for item in app_config.get("apple_ids", []))

    total = 0
    found = False
    for row in reader:
        if units_column not in row:
            available = ", ".join(row.keys())
            raise ConfigError(
                f"Units column '{units_column}' not found in App Store report. Available columns: {available}"
            )
        if product_type_filter:
            product_type = row.get("Product Type Identifier", "")
            if product_type not in product_type_filter:
                continue
        if sku_filter and row.get("SKU") not in sku_filter:
            continue
        if app_apple_id_filter and row.get("Apple Identifier") not in app_apple_id_filter:
            continue
        raw_value = (row.get(units_column) or "0").replace(",", "").strip()
        if not raw_value:
            continue
        total += int(float(raw_value))
        found = True
    if not found:
        raise ConfigError("No matching App Store Connect sales report unit rows found.")
    return total


def google_play_downloads(config: dict[str, Any], play_config: dict[str, Any]) -> tuple[int, list[str]]:
    credentials = make_credentials(config)
    object_name = report_object_name(config, play_config)
    csv_bytes = storage_get_bytes(credentials, play_config["bucket_id"], object_name)
    downloads = parse_installs_metric(
        csv_bytes,
        play_config.get("encoding", "utf-16"),
        play_config.get("metric_column", "Daily User Installs"),
    )
    return downloads, [
        f"Downloaded Google Play report object {object_name}.",
        f"Mapped {downloads} from Google Play {play_config.get('metric_column', 'Daily User Installs')}.",
    ]


def google_play_diagnostic_notes(config: dict[str, Any], play_config: dict[str, Any]) -> list[str]:
    try:
        credentials = make_credentials(config)
        prefix = report_object_prefix(config, play_config)
        names = storage_list_object_names(credentials, play_config["bucket_id"], prefix)
    except ConfigError as error:
        return [f"Google Play diagnostic skipped: {error}"]
    except (HTTPError, URLError) as error:
        return [api_error_note(error, "Google Play object-list diagnostic")]

    if names:
        joined = "; ".join(names)
        return [f"Google Play object-list diagnostic found matching object(s): {joined}"]
    return [
        "Google Play object-list diagnostic succeeded, but found no objects matching "
        f"{prefix}*. This points to a report filename/date mismatch or a report that has not been generated."
    ]


def app_store_downloads(config: dict[str, Any], app_config: dict[str, Any]) -> tuple[int, list[str]]:
    report_bytes = app_store_sales_report_bytes(config, app_config)
    downloads = parse_app_store_units(report_bytes, app_config)
    filters = []
    if app_config.get("apple_ids"):
        filters.append(f"Apple Identifier(s): {', '.join(str(item) for item in app_config['apple_ids'])}")
    if app_config.get("skus"):
        filters.append(f"SKU(s): {', '.join(str(item) for item in app_config['skus'])}")
    return downloads, [
        f"Downloaded App Store Connect {app_config.get('frequency', 'MONTHLY')} {app_config.get('report_type', 'SALES')} report for {app_config.get('report_date') or app_store_report_month(config)}.",
        f"Applied App Store filter(s): {'; '.join(filters) if filters else '<none>'}.",
        f"Mapped {downloads} App Store unit(s) from matching sales report rows.",
    ]


def api_error_note(error: HTTPError | URLError, source: str = "App store source") -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        return f"{source} download error {error.code}: {body or error.reason}"
    return f"{source} connection error: {error.reason}"


def fetch_monthly(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Google Play implementation is scaffolded, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure OAuth, bucket_id, and package_name.",
            ],
        )

    try:
        play_config = config.get("google_play", {})
        app_config = config.get("app_store", {})
        if not play_config.get("enabled", False) and not app_config.get("enabled", False):
            return SourceResult(
                source=SOURCE_NAME,
                implemented=False,
                notes=["Google Play and App Store Connect sources are disabled in config."],
            )

        notes = [f"Loaded app store config from {loaded_path}."]
        values: list[int] = []
        output_config = play_config if play_config.get("enabled", False) else app_config

        if play_config.get("enabled", False):
            try:
                downloads, source_notes = google_play_downloads(config, play_config)
                values.append(downloads)
                notes.extend(source_notes)
            except ConfigError as error:
                notes.append(f"Google Play skipped: {error}")
            except (HTTPError, URLError) as error:
                notes.append(api_error_note(error, "Google Play"))
                notes.extend(google_play_diagnostic_notes(config, play_config))
        elif play_config:
            reason = play_config.get("disabled_reason")
            notes.append(f"Google Play disabled in config.{f' {reason}' if reason else ''}")

        if app_config.get("enabled", False):
            try:
                downloads, source_notes = app_store_downloads(config, app_config)
                values.append(downloads)
                notes.extend(source_notes)
            except ConfigError as error:
                notes.append(f"App Store Connect skipped: {error}")
            except (HTTPError, URLError) as error:
                notes.append(api_error_note(error, "App Store Connect"))
        elif app_config:
            reason = app_config.get("disabled_reason")
            notes.append(f"App Store Connect disabled in config.{f' {reason}' if reason else ''}")

        if not values:
            return SourceResult(
                source=SOURCE_NAME,
                implemented=False,
                notes=notes,
            )

        total_downloads = sum(values)
        notes.append(f"Mapped available app downloads total: {total_downloads}.")

        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=[
                {
                    "source": SOURCE_NAME,
                    "report": "monthly_app_downloads",
                    "sheet": output_config["sheet"],
                    "date_column": output_config["date_column"],
                    "date": scorecard_date(config, output_config),
                    "values": {
                        output_config["scorecard_column"]: total_downloads,
                    },
                }
            ],
            notes=notes,
        )
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch monthly Google Play Console scorecard source data."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to Google Play source config. Defaults to config/sources/optional/google_play.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
