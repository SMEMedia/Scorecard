from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

try:
    from .base import SourceResult
    from .weekly_utils import weekly_date_range
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from sources.base import SourceResult
    from sources.weekly_utils import weekly_date_range


SOURCE_NAME = "Libsyn"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "libsyn.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "examples" / "libsyn.json"


class ConfigError(ValueError):
    pass


class StatsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"th", "td"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._current_cell is not None and self._current_row is not None:
            value = " ".join("".join(self._current_cell).split())
            self._current_row.append(value)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None


class HtmlSummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.forms = 0
        self.tables = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "form":
            self.forms += 1
        elif tag == "table":
            self.tables += 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())


def load_config(config_path: str | Path | None = None) -> tuple[dict[str, Any], Path, bool]:
    configured_path = Path(
        config_path or os.environ.get("SCORECARD_LIBSYN_CONFIG", DEFAULT_CONFIG)
    )
    if configured_path.exists():
        with open(configured_path, "r", encoding="utf-8") as handle:
            return json.load(handle), configured_path, False

    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as handle:
        return json.load(handle), EXAMPLE_CONFIG, True


def load_credentials(config: dict[str, Any]) -> dict[str, str]:
    credentials_file = Path(config.get("credentials_file", ""))
    if not credentials_file.exists():
        raise ConfigError(f"Libsyn credentials file does not exist: {credentials_file}")
    raw = credentials_file.read_text(encoding="utf-8").strip()
    if not raw:
        raise ConfigError(f"Libsyn credentials file is empty: {credentials_file}")
    credentials = json.loads(raw)
    email = credentials.get("email")
    password = credentials.get("password")
    if not email or not password:
        raise ConfigError("Libsyn credentials file needs email and password.")
    return {"email": email, "password": password}


def date_range_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("default_date_range")
    if not raw:
        raise ConfigError("Libsyn config needs default_date_range.")

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
        week_range = weekly_date_range(
            week_ending_weekday=int(raw.get("week_ending_weekday", 5))
        )
        end_offset_days = int(raw.get("end_offset_days", 0))
        start_offset_days = int(raw.get("start_offset_days", 0))
        if start_offset_days:
            start = datetime.fromisoformat(week_range["start_date"]).date()
            week_range["start_date"] = (
                start + timedelta(days=start_offset_days)
            ).isoformat()
        if end_offset_days:
            end = datetime.fromisoformat(week_range["end_date"]).date()
            week_range["end_date"] = (end + timedelta(days=end_offset_days)).isoformat()
        return week_range

    if "start_date" not in raw or "end_date" not in raw:
        raise ConfigError("Date range needs start_date/end_date or a supported mode.")
    return raw


def target_date_range(config: dict[str, Any]) -> tuple[date, date]:
    target = date_range_config(config)
    return (
        datetime.fromisoformat(target["start_date"]).date(),
        datetime.fromisoformat(target["end_date"]).date(),
    )


def scorecard_date(config: dict[str, Any]) -> str:
    raw = date_range_config(config)
    if raw.get("scorecard_date"):
        return raw["scorecard_date"]
    start = datetime.fromisoformat(raw["start_date"]).date()
    if config.get("date_grain") == "week":
        return raw["end_date"]
    return date(start.year, start.month, 1).isoformat()


def make_opener(config: dict[str, Any]) -> Any:
    cookie_file = Path(config.get("cookie_file") or PROJECT_ROOT / "config" / "state" / "libsyn_cookie.txt")
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_jar = MozillaCookieJar(str(cookie_file))
    opener = build_opener(HTTPCookieProcessor(cookie_jar))

    credentials = load_credentials(config)
    login_url = config.get("login_url", "https://login.libsyn.com/")
    request = Request(
        login_url,
        data=urlencode(credentials).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with opener.open(request, timeout=60) as response:
        response.read()
    cookie_jar.save(ignore_discard=True, ignore_expires=True)
    return opener


def export_url(config: dict[str, Any]) -> str:
    direct_url = config.get("export_url")
    if direct_url:
        return str(direct_url)

    show_id = config.get("show_id")
    if not show_id:
        raise ConfigError("Libsyn config needs show_id or export_url.")
    template = config.get(
        "export_url_template",
        "https://four.libsyn.com/stats/ajax-export/show_id/{show_id}/type/{export_type}/target/show/id/{show_id}",
    )
    return template.format(
        show_id=show_id,
        export_type=config.get("export_type", "monthly"),
    )


def download_csv(
    config: dict[str, Any],
    config_path: str | Path | None = None,
) -> str:
    csv_file = config.get("csv_file")
    if csv_file:
        path = Path(csv_file)
        if not path.exists():
            raise ConfigError(f"Libsyn CSV file does not exist: {path}")
        return read_export_text(path, config)

    if config.get("browser_export_enabled"):
        cached_path = cached_export_path(config)
        if cached_path:
            cleanup_cached_exports(config, keep_path=cached_path)
            return read_export_text(cached_path, config)
        exported_path = download_with_playwright(config, config_path)
        cleanup_cached_exports(config, keep_path=exported_path)
        return read_export_text(exported_path, config)

    opener = make_opener(config)
    request = Request(export_url(config), method="GET")
    with opener.open(request, timeout=60) as response:
        body = response.read()
    return body.decode(config.get("csv_encoding", "utf-8-sig"))


def read_export_text(path: Path, config: dict[str, Any]) -> str:
    """Read Libsyn's plain CSV or its ZIP archive mislabeled with a .csv suffix."""
    encoding = config.get("csv_encoding", "utf-8-sig")
    if not zipfile.is_zipfile(path):
        return path.read_text(encoding=encoding)

    try:
        with zipfile.ZipFile(path) as archive:
            csv_members = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith(".csv")
            ]
            summary_members = [
                name for name in csv_members if "by episode" not in name.lower()
            ]
            if not summary_members:
                raise ConfigError(
                    f"Libsyn ZIP export did not contain a summary CSV: {path}"
                )
            return archive.read(summary_members[0]).decode(encoding)
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as error:
        raise ConfigError(f"Could not read Libsyn ZIP export {path}: {error}") from error


def browser_downloads_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("browser_downloads_dir") or PROJECT_ROOT / "outputs" / "libsyn")


def cached_export_files(config: dict[str, Any]) -> list[Path]:
    folder = browser_downloads_dir(config)
    if not folder.exists():
        return []
    pattern = config.get("browser_export_glob", "libsyn-downloads-*.csv")
    return sorted(folder.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)


def export_covers_target_month(config: dict[str, Any], path: Path) -> bool:
    rows = parse_rows(read_export_text(path, config))
    start, end = target_date_range(config)
    daily_dates = [
        parsed
        for row in rows
        if row.get("__section") == config.get("data_section", "Daily Downloads")
        for parsed in [row_date(row, config.get("date_columns", ["Total", "Date"]))]
        if parsed is not None
    ]
    return bool(daily_dates) and min(daily_dates) <= start and max(daily_dates) >= end


def cached_export_path(config: dict[str, Any]) -> Path | None:
    if not config.get("browser_cache_enabled", True):
        return None
    for path in cached_export_files(config):
        try:
            if export_covers_target_month(config, path):
                return path
        except (OSError, UnicodeDecodeError, ConfigError, csv.Error):
            continue
    return None


def cleanup_cached_exports(config: dict[str, Any], keep_path: Path) -> None:
    keep_resolved = keep_path.resolve()
    folder = browser_downloads_dir(config).resolve()
    for path in cached_export_files(config):
        resolved = path.resolve()
        if resolved == keep_resolved:
            continue
        if folder not in resolved.parents:
            continue
        path.unlink(missing_ok=True)


def download_with_playwright(
    config: dict[str, Any],
    config_path: str | Path | None = None,
) -> Path:
    helper = PROJECT_ROOT / "scripts" / "sources" / "libsyn_export_browser.py"
    resolved_config_path = Path(
        config_path
        or os.environ.get("SCORECARD_LIBSYN_CONFIG", DEFAULT_CONFIG)
    )
    timeout_seconds = int(config.get("browser_subprocess_timeout_seconds", 300))
    try:
        completed = subprocess.run(
            [sys.executable, str(helper), "--config", str(resolved_config_path)],
            check=False,
            stdout=subprocess.PIPE,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise ConfigError(
            "Libsyn Playwright export timed out after "
            f"{timeout_seconds} seconds while using {resolved_config_path}."
        ) from error
    if completed.returncode != 0:
        raise ConfigError(
            "Libsyn Playwright export failed: "
            f"{completed.stdout.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ConfigError(f"Libsyn Playwright export returned invalid JSON: {error}") from error
    if not payload.get("ok"):
        raise ConfigError(f"Libsyn Playwright export failed: {payload.get('error')}")
    path = Path(payload["path"])
    if not path.exists():
        raise ConfigError(f"Libsyn Playwright export did not create file: {path}")
    return path


def html_tables_to_rows(html_text: str) -> list[dict[str, str]]:
    parser = StatsTableParser()
    parser.feed(html_text)
    for table in parser.tables:
        if not table:
            continue
        headers = table[0]
        if "Date" not in headers:
            continue
        rows = []
        for raw_row in table[1:]:
            row = {
                headers[idx]: raw_row[idx]
                for idx in range(min(len(headers), len(raw_row)))
            }
            rows.append(row)
        if rows:
            return rows
    raise ConfigError("Libsyn HTML response did not include a table with a Date column.")


def parse_rows(response_text: str) -> list[dict[str, str]]:
    stripped = response_text.strip()
    if not stripped:
        raise ConfigError("Libsyn export returned an empty response.")
    if stripped.lower().startswith("<!doctype html") or stripped.lower().startswith("<html"):
        return html_tables_to_rows(stripped)
    reader = csv.reader(stripped.splitlines())
    try:
        headers = next(reader)
    except StopIteration:
        return []

    rows = []
    section = ""
    for raw_row in reader:
        if not any(cell.strip() for cell in raw_row):
            continue
        padded = raw_row + [""] * (len(headers) - len(raw_row))
        row = {headers[idx]: padded[idx] for idx in range(len(headers))}
        first_cell = (padded[0] if padded else "").strip()
        metric_cells = padded[1:]
        if first_cell and not any(cell.strip() for cell in metric_cells):
            section = first_cell
            continue
        row["__section"] = section
        rows.append(row)
    return rows


def response_summary(response_text: str) -> dict[str, Any]:
    stripped = response_text.strip()
    if stripped.lower().startswith("<!doctype html") or stripped.lower().startswith("<html"):
        parser = HtmlSummaryParser()
        parser.feed(stripped)
        return {
            "response_type": "html",
            "title": parser.title,
            "forms": parser.forms,
            "tables": parser.tables,
            "contains_date_text": "Date" in stripped,
            "contains_iab_downloads_text": "IAB Downloads" in stripped,
            "contains_access_token": "access_token" in stripped,
            "contains_base_api_url": "base_api_url" in stripped,
            "contains_show_id": "show_id" in stripped,
        }
    reader = csv.reader(stripped.splitlines())
    try:
        headers = next(reader)
    except StopIteration:
        headers = []
    return {
        "response_type": "csv_or_text",
        "headers": headers,
    }


def endpoint_hints(response_text: str) -> list[str]:
    patterns = re.findall(
        r"""(?:https?:)?//[^"']+|/[A-Za-z0-9_./?=&%-]*(?:export|download|stats|assets)[A-Za-z0-9_./?=&%-]*""",
        response_text,
        flags=re.IGNORECASE,
    )
    hints = []
    for pattern in patterns:
        if pattern not in hints:
            hints.append(pattern)
    return hints[:100]


def absolute_libsyn_url(path_or_url: str) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    if path_or_url.startswith("//"):
        return f"https:{path_or_url}"
    if path_or_url.startswith("/") and path_or_url.endswith(".js") and not path_or_url.startswith("/assets/"):
        return f"https://five.libsyn.com/assets{path_or_url}"
    if path_or_url.startswith("/"):
        return f"https://five.libsyn.com{path_or_url}"
    return f"https://five.libsyn.com/{path_or_url}"


def javascript_assets(response_text: str) -> list[str]:
    assets = []
    for hint in endpoint_hints(response_text):
        clean_hint = hint.split('"')[0].split("'")[0]
        if clean_hint.endswith(".js") and "libsyn.com" not in clean_hint and clean_hint.startswith("/assets/"):
            assets.append(absolute_libsyn_url(clean_hint))
    return assets


def asset_endpoint_hints(asset_text: str) -> list[str]:
    patterns = re.findall(
        r"""(?:https?:)?//[^"'`]+|/[A-Za-z0-9_./{}?$&=:%,-]+""",
        asset_text,
    )
    hints = []
    for pattern in patterns:
        if len(pattern) > 300:
            continue
        lowered = pattern.lower()
        if not any(term in lowered for term in ["stat", "export", "download", "report", "show"]):
            continue
        if pattern not in hints:
            hints.append(pattern)
    return hints[:300]


def page_context_hints(response_text: str) -> dict[str, Any]:
    hints: dict[str, Any] = {}
    for key in ["base_api_url", "api_version", "access_token", "show_id", "show_title"]:
        match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', response_text)
        if match:
            value = match.group(1)
            hints[key] = "<present>" if key == "access_token" else value
            continue
        match = re.search(rf"{key}\s*:\s*['\"]([^'\"]*)['\"]", response_text)
        if match:
            value = match.group(1)
            hints[key] = "<present>" if key == "access_token" else value
    return hints


def numeric_value(raw: Any) -> int:
    text = str(raw or "0").replace(",", "").strip()
    return int(float(text)) if text else 0


def row_date(row: dict[str, str], date_columns: list[str]) -> date | None:
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"]
    for column in date_columns:
        raw = row.get(column)
        if not raw:
            continue
        for fmt in formats:
            try:
                return datetime.strptime(raw.strip(), fmt).date()
            except ValueError:
                continue
    return None


def downloads_total(config: dict[str, Any], rows: list[dict[str, str]]) -> int:
    metric_column = config.get("metric_column", "IAB Downloads")
    date_columns = config.get("date_columns", ["date", "day", "month", "item_release_date"])
    data_section = config.get("data_section", "Daily Downloads")
    start, end = target_date_range(config)

    dated_rows = []
    undated_total = 0
    for row in rows:
        if data_section and row.get("__section") != data_section:
            continue
        if metric_column not in row:
            available = ", ".join(row.keys())
            raise ConfigError(
                f"Metric column '{metric_column}' not found in Libsyn CSV. Available columns: {available}"
            )
        parsed_date = row_date(row, date_columns)
        if parsed_date is None:
            undated_total += numeric_value(row[metric_column])
            continue
        if start <= parsed_date <= end:
            dated_rows.append(row)

    if dated_rows:
        return sum(numeric_value(row[metric_column]) for row in dated_rows)

    if config.get("allow_undated_export_total", False):
        return undated_total

    raise ConfigError(
        "Libsyn CSV did not include rows with recognizable dates in the target date range. "
        "Run with --diagnose to inspect CSV headers and sample rows."
    )


def diagnose(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Libsyn diagnostics are ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure credentials/show_id.",
            ],
        )

    try:
        csv_text = download_csv(config, loaded_path)
        rows = parse_rows(csv_text)
        sample_size = int(config.get("diagnostic_sample_rows", 5))
        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=[
                {
                    "headers": list(rows[0].keys()) if rows else [],
                    "sample_rows": rows[:sample_size],
                }
            ],
            notes=[
                f"Loaded Libsyn config from {loaded_path}.",
                f"Downloaded {len(rows)} Libsyn CSV row(s).",
                "Diagnostic output intentionally does not write to the Google Sheet.",
            ],
        )
    except ConfigError as error:
        try:
            csv_text = download_csv(config, loaded_path)
            return SourceResult(
                source=SOURCE_NAME,
                implemented=False,
                records=[response_summary(csv_text)],
                notes=[str(error)],
            )
        except Exception:
            return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def api_error_note(error: HTTPError | URLError) -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        return f"Libsyn export error {error.code}: {body or error.reason}"
    return f"Libsyn connection error: {error.reason}"


def inspect_page(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Libsyn page inspection is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure credentials/export_url.",
            ],
        )

    try:
        response_text = download_csv(config, loaded_path)
        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=[
                {
                    "summary": response_summary(response_text),
                    "context_hints": page_context_hints(response_text),
                    "endpoint_hints": endpoint_hints(response_text),
                }
            ],
            notes=[
                f"Loaded Libsyn config from {loaded_path}.",
                "Inspected response for export/download/stats endpoint hints.",
            ],
        )
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def inspect_assets(config_path: str | Path | None = None) -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Libsyn asset inspection is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure credentials/export_url.",
            ],
        )

    try:
        page_text = download_csv(config, loaded_path)
        assets = javascript_assets(page_text)
        inspected_assets = set()
        records = []
        while assets:
            asset_url = assets.pop(0)
            if asset_url in inspected_assets:
                continue
            inspected_assets.add(asset_url)
            with urlopen(Request(asset_url, method="GET"), timeout=60) as response:
                asset_text = response.read().decode("utf-8", errors="replace")
            hints = asset_endpoint_hints(asset_text)
            records.append(
                {
                    "asset": asset_url,
                    "hints": hints,
                }
            )
            for hint in hints:
                if not hint.endswith(".js"):
                    continue
                next_asset = absolute_libsyn_url(hint)
                if next_asset not in inspected_assets and next_asset not in assets:
                    assets.append(next_asset)
        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=records,
            notes=[
                f"Loaded Libsyn config from {loaded_path}.",
                f"Inspected {len(records)} Libsyn JavaScript asset(s).",
            ],
        )
    except ConfigError as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[str(error)])
    except (HTTPError, URLError) as error:
        return SourceResult(source=SOURCE_NAME, implemented=False, notes=[api_error_note(error)])


def _fetch(config_path: str | Path | None = None, cadence: str = "monthly") -> SourceResult:
    config, loaded_path, used_example = load_config(config_path)
    if used_example:
        return SourceResult(
            source=SOURCE_NAME,
            implemented=False,
            notes=[
                f"Libsyn {cadence} implementation is ready, but no config file exists at {DEFAULT_CONFIG}.",
                f"Copy {loaded_path} to {DEFAULT_CONFIG} and configure credentials/show_id.",
            ],
        )

    try:
        csv_text = download_csv(config, loaded_path)
        rows = parse_rows(csv_text)
        downloads = downloads_total(config, rows)
        return SourceResult(
            source=SOURCE_NAME,
            implemented=True,
            records=[
                {
                    "source": SOURCE_NAME,
                    "report": f"{cadence}_podcast_downloads",
                    "sheet": config["sheet"],
                    "date_column": config["date_column"],
                    "date": scorecard_date(config),
                    "values": {
                        config["scorecard_column"]: downloads,
                    },
                }
            ],
            notes=[
                f"Loaded Libsyn config from {loaded_path}.",
                f"Downloaded {len(rows)} Libsyn CSV row(s).",
                f"Mapped {downloads} downloads to {config['scorecard_column']}.",
            ],
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
    parser = argparse.ArgumentParser(description="Fetch Libsyn podcast downloads.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to Libsyn source config. Defaults to config/sources/monthly/libsyn.json.",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Download the Libsyn CSV and print headers/sample rows without returning scorecard records.",
    )
    parser.add_argument(
        "--inspect-page",
        action="store_true",
        help="Inspect the configured Libsyn page for export/download/stats endpoint hints.",
    )
    parser.add_argument(
        "--inspect-assets",
        action="store_true",
        help="Inspect Libsyn page JavaScript assets for route/API endpoint hints.",
    )
    parser.add_argument("--weekly", action="store_true", help="Fetch weekly records.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.inspect_page:
        result = inspect_page(args.config)
    elif args.inspect_assets:
        result = inspect_assets(args.config)
    elif args.diagnose:
        result = diagnose(args.config)
    else:
        result = fetch_weekly(args.config) if args.weekly else fetch_monthly(args.config)
    print(json.dumps(result.__dict__, indent=2, default=str))


if __name__ == "__main__":
    main()
