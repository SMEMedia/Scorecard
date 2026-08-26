from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_METADATA_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"
AUTOMATED_FILL = {
    "red": 0.8862745,
    "green": 0.9372549,
    "blue": 0.85882354,
}
DATA_SHEET_BY_KEY = {
    ("monthly", "SME Media Data"): "Monthly Media Data",
    ("monthly", "SME Media Data (Detail)"): "Monthly Media Detail",
    ("monthly", "SME Media Engagement Metrics"): "Monthly Engagement",
    ("weekly", "SME Media Data"): "Weekly Media Data",
}
SEARCH_HEADER_BLOCK = [
    "Search Clicks",
    "GA4 Search Clicks",
    "Google Search Console Search Clicks",
    "Search Impressions",
    "GA4 Search Impressions",
    "Google Search Console Search Impressions",
]
EXPECTED_HEADERS_BY_TAB = {
    "Monthly Media Data": [
        "Month",
        "AM Sessions",
        "AM Page Views",
        "AM Users",
        "AM New Users",
        "AM Return Users",
        "AM New User %%",
        "AM Return User %%",
        "AM Sessions / User",
        "AM Page Views / Session",
        "eEdition Visits",
        "eEdition Users",
        "eEdition Page Views",
        "Print Subscribers",
        "Digital e-Editions Subscribers",
        "Total Magazine subscribers",
        "App Sessions",
        "App Views",
        "App Users",
        "App New Users",
        "App Return Users",
        "Monthly App Downloads",
        "Total App Downloads",
        "Podcast Downloads",
        "YouTube Podcast Plays",
        "AM Web Podcast Plays",
        "Podcast Total",
        "YouTube Video Plays",
        "Search Clicks",
        "GA4 Search Clicks",
        "Google Search Console Search Clicks",
        "Search Impressions",
        "GA4 Search Impressions",
        "Google Search Console Search Impressions",
        "Ave Search Position",
        "Search CTR",
        "Email Subscribers",
        "Emails Delivered",
        "Email Opens",
        "Email Open Rate",
        "Email Clicks",
        "Email CTR",
        "Email Click to Open Rate",
        "Email Starts",
        "Email Stops",
        "Email Net Subs",
        "Facebook Followers",
        "YouTube Subscribers",
        "LinkedIn Followers",
        "X Followers",
        "Instagram Followers",
        "Threads Followers",
        "New IOs (Count)",
        "New IOs (Revenue)",
        "Rev / IO",
    ],
    "Monthly Media Detail": [
        "Month Ending",
        "Session Medium None / Not Set",
        "Session Medium (Cross-network)",
        "Session Medium (Direct)",
        "Session Medium (Email)",
        "Session Medium (Organic Search)",
        "Session Medium (Referral)",
        "Session Medium (Paid Search)",
        "Session Medium (Organic Social)",
        "Session Medium (Paid Social)",
        "Session Medium (Video)",
        "LinkedIn Impressions (Organic)",
        "LinkedIn Impressions (Paid)",
        "LinkedIn Reach",
        "LinkedIn Clicks (Oragnic)",
        "LinkedIn Clicks (Paid)",
        "LinkedIn Reactions (Organic)",
        "LinkedIn Reactions (Paid)",
        "LinkenIn Comments (Organic)",
        "LinkenIn Comments (Paid)",
        "LinkedIn Reposts (Organic)",
        "LinkedIn Reposts (Paid)",
        "LinkedIn Engagement Rate (Organic)",
        "LinkedIn Engagement Rate (Paid)",
        "LinkedIn Posts",
    ],
    "Monthly Engagement": [
        "Month",
        "AM.org Total Users (#)",
        "AM.org Return Users (#)",
        "AM.org Return Users (%)",
        "Sessions ",
        "Sessions Per User",
        "Engagement Rate (%)",
        "Engaged Total Users (user_engagement)",
        "Engaged Total Users %",
        "Scroll Total Users (90% page depth)",
        "% Scroll Users from Total",
        "Videos Views*",
        "Avg. View Duration*",
        "Watch Time (Hours)*",
    ],
    "Weekly Media Data": [
        "Week Ending",
        "AM Sessions",
        "AM Page Views",
        "AM Users",
        "AM New Users",
        "AM Return Users",
        "AM New User %%",
        "AM Return User %%",
        "AM Sessions / User",
        "AM Page Views / Session",
        "App Sessions",
        "App Views",
        "App Users",
        "App New Users",
        "App Return Users",
        "Podcast Downloads",
        "YouTube Podcast Plays",
        "AM Web Podcast Plays",
        "Podcast Total",
        "YouTube Video Plays",
        "Search Clicks",
        "GA4 Search Clicks",
        "Google Search Console Search Clicks",
        "Search Impressions",
        "GA4 Search Impressions",
        "Google Search Console Search Impressions",
        "Ave Search Position",
        "Search CTR",
        "Emails Delivered",
        "Email Opens",
        "Email Open Rate",
        "Email Clicks",
        "Email CTR",
        "Email Click to Open Rate",
        "New IOs (Count)",
        "New IOs (Revenue)",
        "Rev / IO",
        "Pipeline (10)",
        "Pipeline (10v)",
        "Pipeline (50)",
        "Pipeline (50v)",
        "Pipeline (90)",
        "Pipeline (90v)",
        "Pipeline Total",
        "Pipeline Total (Tv)",
    ],
}


class GoogleSheetsError(RuntimeError):
    pass


def normalize_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        normalized = value.replace(" 0:", " 00:")
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            if " " in normalized:
                date_part = normalized.split(" ", 1)[0]
                try:
                    return datetime.fromisoformat(date_part).date()
                except ValueError:
                    pass
            else:
                date_part = normalized
            for date_format in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    return datetime.strptime(date_part, date_format).date()
                except ValueError:
                    continue
            raise
    raise ValueError(f"Unsupported date value: {value!r}")


def data_sheet_name(cadence: str, scorecard_sheet: str) -> str:
    try:
        return DATA_SHEET_BY_KEY[(cadence, scorecard_sheet)]
    except KeyError as error:
        raise ValueError(
            f"No Google Sheets tab mapping for {cadence} {scorecard_sheet}."
        ) from error


def make_credentials(service_account_file: str | Path) -> service_account.Credentials:
    return service_account.Credentials.from_service_account_file(
        str(service_account_file),
        scopes=[SHEETS_SCOPE, DRIVE_METADATA_SCOPE],
    )


def authorized_request(
    credentials: service_account.Credentials,
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())

    data = None
    headers = {"Authorization": f"Bearer {credentials.token}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        try:
            body = error.read().decode("utf-8")
        except Exception:
            body = ""
        raise GoogleSheetsError(f"Google API error {error.code}: {body}") from error
    except URLError as error:
        raise GoogleSheetsError(f"Google API connection error: {error.reason}") from error

    return json.loads(body) if body else {}


def resolve_spreadsheet_id(
    credentials: service_account.Credentials,
    spreadsheet_id: str | None = None,
    title: str = "Scorecard",
) -> str:
    if spreadsheet_id:
        return spreadsheet_id

    query = (
        "mimeType='application/vnd.google-apps.spreadsheet' "
        f"and name='{title.replace(chr(39), chr(92) + chr(39))}' and trashed=false"
    )
    params = urlencode(
        {
            "q": query,
            "fields": "files(id,name,modifiedTime)",
            "pageSize": "10",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
    )
    payload = authorized_request(credentials, f"{DRIVE_FILES_API}?{params}")
    files = payload.get("files", [])
    if not files:
        raise GoogleSheetsError(
            f"Could not find a shared Google Sheet titled '{title}' for the service account."
        )
    exact = [item for item in files if item.get("name") == title]
    if len(exact) > 1:
        names = ", ".join(item["id"] for item in exact)
        raise GoogleSheetsError(
            f"Found multiple Google Sheets titled '{title}'. Configure spreadsheet_id explicitly. IDs: {names}"
        )
    return (exact or files)[0]["id"]


def spreadsheet_metadata(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
) -> dict[str, Any]:
    return authorized_request(
        credentials,
        f"{SHEETS_API}/{spreadsheet_id}?fields=spreadsheetId,spreadsheetUrl,sheets.properties,sheets.tables",
    )


def ensure_tabs(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    tab_names: set[str],
) -> dict[str, Any]:
    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    existing = {
        sheet["properties"]["title"]
        for sheet in metadata.get("sheets", [])
    }
    missing = sorted(tab_names - existing)
    if missing:
        requests = [
            {"addSheet": {"properties": {"title": name}}}
            for name in missing
        ]
        authorized_request(
            credentials,
            f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
            method="POST",
            payload={"requests": requests},
        )
        metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    return metadata


def quote_sheet_name(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def get_values(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    tab_name: str,
) -> list[list[Any]]:
    range_name = f"{quote_sheet_name(tab_name)}!A:ZZ"
    url = f"{SHEETS_API}/{spreadsheet_id}/values/{quote(range_name, safe='')}?majorDimension=ROWS"
    payload = authorized_request(credentials, url)
    return payload.get("values", [])


def put_values(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    tab_name: str,
    values: list[list[Any]],
) -> None:
    range_name = f"{quote_sheet_name(tab_name)}!A1"
    url = f"{SHEETS_API}/{spreadsheet_id}/values/{quote(range_name, safe='')}?valueInputOption=USER_ENTERED"
    authorized_request(
        credentials,
        url,
        method="PUT",
        payload={"majorDimension": "ROWS", "values": values},
    )


def clear_values(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    tab_name: str,
) -> None:
    range_name = f"{quote_sheet_name(tab_name)}!A:ZZ"
    authorized_request(
        credentials,
        f"{SHEETS_API}/{spreadsheet_id}/values/{quote(range_name, safe='')}:clear",
        method="POST",
        payload={},
    )


def sheet_metadata_by_title(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        sheet["properties"]["title"]: sheet
        for sheet in metadata.get("sheets", [])
    }


def table_name_for_tab(tab_name: str) -> str:
    return "".join(part for part in tab_name.title() if part.isalnum())


def table_range(sheet_id: int, row_count: int, column_count: int) -> dict[str, int]:
    return {
        "sheetId": sheet_id,
        "startRowIndex": 0,
        "endRowIndex": max(row_count, 1),
        "startColumnIndex": 0,
        "endColumnIndex": max(column_count, 1),
    }


def is_percent_header(header: str) -> bool:
    normalized = header.strip()
    return (
        "Rate" in normalized
        or normalized.endswith("CTR")
        or normalized.endswith("%%")
        or normalized.endswith("(%)")
        or normalized.endswith(" %")
        or normalized.startswith("% ")
    )


def number_format_for_header(header: str, column_index: int) -> tuple[str, str] | None:
    if column_index == 0:
        return "DATE", "M/d/yyyy"
    if header == "Avg. View Duration*":
        return "TEXT", "@"

    return None


def table_column_properties(headers: list[str]) -> list[dict[str, Any]]:
    columns = []
    for idx, header in enumerate(headers):
        if idx == 0:
            column_type = "DATE"
        elif header == "Avg. View Duration*":
            column_type = "TEXT"
        elif is_percent_header(header):
            column_type = "PERCENT"
        else:
            column_type = "DOUBLE"
        columns.append(
            {
                "columnIndex": idx,
                "columnName": header,
                "columnType": column_type,
            }
        )
    return columns


def ensure_table(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    tab_name: str,
    headers: list[str],
    row_count: int,
) -> None:
    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    sheet = sheet_metadata_by_title(metadata).get(tab_name)
    if not sheet:
        raise GoogleSheetsError(f"Cannot create/update table; tab not found: {tab_name}")

    sheet_id = sheet["properties"]["sheetId"]
    table = (sheet.get("tables") or [None])[0]
    body = {
        "name": table.get("name") if table else table_name_for_tab(tab_name),
        "range": table_range(sheet_id, row_count, len(headers)),
        "columnProperties": table_column_properties(headers),
    }
    if table:
        body["tableId"] = table["tableId"]
        request = {
            "updateTable": {
                "table": body,
                "fields": "range,columnProperties",
            }
        }
    else:
        request = {"addTable": {"table": body}}

    authorized_request(
        credentials,
        f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
        method="POST",
        payload={"requests": [request]},
    )


def format_scorecard_columns(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    tab_name: str,
    headers: list[str],
    row_count: int,
) -> None:
    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    sheet = sheet_metadata_by_title(metadata).get(tab_name)
    if not sheet:
        raise GoogleSheetsError(f"Cannot format columns; tab not found: {tab_name}")

    sheet_id = sheet["properties"]["sheetId"]
    requests = []
    for column_index, header in enumerate(headers):
        number_format = number_format_for_header(header, column_index)
        if not number_format:
            continue
        format_type, pattern = number_format
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": max(row_count, 2),
                        "startColumnIndex": column_index,
                        "endColumnIndex": column_index + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": format_type,
                                "pattern": pattern,
                            }
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

    if requests:
        authorized_request(
            credentials,
            f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
            method="POST",
            payload={"requests": requests},
        )


def format_automated_cells(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    ranges: list[dict[str, int]],
) -> None:
    requests = []
    for grid_range in ranges:
        requests.append(
            {
                "repeatCell": {
                    "range": grid_range,
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColorStyle": {
                                "rgbColor": AUTOMATED_FILL
                            }
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColorStyle",
                }
            }
        )

    if requests:
        authorized_request(
            credentials,
            f"{SHEETS_API}/{spreadsheet_id}:batchUpdate",
            method="POST",
            payload={"requests": requests},
        )


def parse_existing_table(rows: list[list[Any]], date_column: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    headers = list(rows[0]) if rows else [date_column]
    if not headers:
        headers = [date_column]
    headers[0] = headers[0] or date_column
    if date_column not in headers:
        headers[0] = date_column

    records: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        date_key = normalize_date(str(row[0])).isoformat()
        values = {}
        for idx, value in enumerate(row[1:], start=1):
            if idx < len(headers) and headers[idx]:
                values[headers[idx]] = value
        records[date_key] = values
    return headers, records


def ensure_expected_headers(tab_name: str, headers: list[str]) -> list[str]:
    expected_headers = EXPECTED_HEADERS_BY_TAB.get(tab_name)
    if expected_headers:
        extras = [
            header for header in headers
            if header and header not in expected_headers
        ]
        return expected_headers + extras

    if tab_name not in {"Monthly Media Data", "Weekly Media Data"}:
        return headers
    if all(header in headers for header in SEARCH_HEADER_BLOCK):
        return headers

    insert_at = len(headers)
    for anchor in (
        "Google Search Console Search Clicks",
        "Google Search Console Search Impressions",
        "Ave Search Position",
        "Search CTR",
    ):
        if anchor in headers:
            insert_at = min(insert_at, headers.index(anchor))

    search_headers_before_insert = sum(
        1
        for header in headers[:insert_at]
        if header in SEARCH_HEADER_BLOCK
    )
    adjusted_insert_at = insert_at - search_headers_before_insert
    headers_without_search_block = [
        header for header in headers
        if header not in SEARCH_HEADER_BLOCK
    ]
    return (
        headers_without_search_block[:adjusted_insert_at]
        + SEARCH_HEADER_BLOCK
        + headers_without_search_block[adjusted_insert_at:]
    )


def serializable_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    return value


def values_equivalent(left: Any, right: Any) -> bool:
    if left in ("", None) and right in ("", None):
        return True
    if left == right:
        return True

    def comparable_number(value: Any) -> float | None:
        parsed_time: time | None = None
        if isinstance(value, time):
            parsed_time = value
        elif isinstance(value, str) and value.lstrip("'").count(":") == 2:
            try:
                parsed_time = time.fromisoformat(value.lstrip("'").zfill(8))
            except ValueError:
                pass
        if parsed_time is not None:
            return (
                parsed_time.hour * 3600
                + parsed_time.minute * 60
                + parsed_time.second
            ) / 86400
        return number_value(value)

    left_number = comparable_number(left)
    right_number = comparable_number(right)
    if left_number is not None and right_number is not None:
        return abs(left_number - right_number) <= max(
            1e-9,
            abs(left_number) * 1e-9,
        )
    return False


ERROR_STRINGS = {"#DIV/0!", "#VALUE!", "#REF!", "#N/A", "#NAME?", "#NUM!", "#ERROR!"}


def clean_formula_value(value: Any) -> Any:
    if isinstance(value, str) and value.split(" ", 1)[0] in ERROR_STRINGS:
        return ""
    return value


def number_value(value: Any) -> float | None:
    value = clean_formula_value(value)
    if value in ("", None):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.replace(",", "").strip()
        if normalized.endswith("%"):
            normalized = normalized[:-1]
            try:
                return float(normalized) / 100
            except ValueError:
                return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def normalize_scorecard_value(header: str, value: Any) -> Any:
    if header == "Avg. View Duration*":
        return value
    number = number_value(value)
    if number is None:
        return value
    if header.startswith("Session Medium"):
        return int(round(number))
    if is_percent_header(header):
        if abs(number) > 1:
            number /= 100
        return round(number, 3)
    if isinstance(value, float) or (isinstance(value, str) and "." in value):
        return round(number, 3)
    return value


def ratio_value(
    values: dict[str, Any],
    numerator_header: str,
    denominator_header: str,
) -> float | str:
    numerator = number_value(values.get(numerator_header))
    denominator = number_value(values.get(denominator_header))
    if numerator is None or denominator in (None, 0):
        return ""
    return numerator / denominator


def sum_if_any(values: dict[str, Any], headers: list[str]) -> float | str:
    numbers = [
        number
        for number in (number_value(values.get(header)) for header in headers)
        if number is not None
    ]
    if not numbers:
        return ""
    return sum(numbers)


def difference_if_any(
    values: dict[str, Any],
    left_header: str,
    right_header: str,
) -> float | str:
    left = number_value(values.get(left_header))
    right = number_value(values.get(right_header))
    if left is None and right is None:
        return ""
    return (left or 0) - (right or 0)


def normalize_formula_owned_cells(
    headers: list[str],
    records: dict[str, dict[str, Any]],
    formula_columns: set[str],
    target_dates: set[str],
) -> None:
    for date_key, values in records.items():
        if date_key not in target_dates:
            continue
        for header in formula_columns:
            if header in values:
                values[header] = clean_formula_value(values[header])

    for date_key in sorted(records):
        if date_key not in target_dates:
            continue
        values = records[date_key]
        if "AM New User %%" in formula_columns:
            values["AM New User %%"] = ratio_value(values, "AM New Users", "AM Users")
        if "AM Return User %%" in formula_columns:
            values["AM Return User %%"] = ratio_value(
                values,
                "AM Return Users",
                "AM Users",
            )
        if "AM Sessions / User" in formula_columns:
            values["AM Sessions / User"] = ratio_value(values, "AM Sessions", "AM Users")
        if "AM Page Views / Session" in formula_columns:
            values["AM Page Views / Session"] = ratio_value(
                values,
                "AM Page Views",
                "AM Sessions",
            )
        if "Podcast Total" in formula_columns:
            values["Podcast Total"] = sum_if_any(
                values,
                ["Podcast Downloads", "YouTube Podcast Plays", "AM Web Podcast Plays"],
            )
        if "Email Open Rate" in formula_columns:
            values["Email Open Rate"] = ratio_value(
                values,
                "Email Opens",
                "Emails Delivered",
            )
        if "Email CTR" in formula_columns:
            values["Email CTR"] = ratio_value(values, "Email Clicks", "Emails Delivered")
        if "Email Click to Open Rate" in formula_columns:
            values["Email Click to Open Rate"] = ratio_value(
                values,
                "Email Clicks",
                "Email Opens",
            )
        if "Email Net Subs" in formula_columns:
            values["Email Net Subs"] = difference_if_any(
                values,
                "Email Starts",
                "Email Stops",
            )
        if "Rev / IO" in formula_columns:
            values["Rev / IO"] = ratio_value(values, "New IOs (Revenue)", "New IOs (Count)")

        if "YouTube Video Plays" in formula_columns:
            values["YouTube Video Plays"] = clean_formula_value(
                values.get("YouTube Video Plays", "")
            )
            if number_value(values["YouTube Video Plays"]) == 0:
                values["YouTube Video Plays"] = ""

    if "Total App Downloads" in formula_columns:
        previous_total: float | None = None
        for date_key in sorted(records):
            values = records[date_key]
            existing_total = number_value(values.get("Total App Downloads"))
            monthly_downloads = number_value(values.get("Monthly App Downloads"))
            if date_key in target_dates and monthly_downloads is not None:
                values["Total App Downloads"] = (previous_total or 0) + monthly_downloads
                previous_total = number_value(values["Total App Downloads"])
            elif existing_total is not None:
                previous_total = existing_total


def build_rows(headers: list[str], records: dict[str, dict[str, Any]]) -> list[list[Any]]:
    rows = [headers]
    for date_key in sorted(records):
        values = records[date_key]
        rows.append([date_key] + [serializable_value(values.get(header, "")) for header in headers[1:]])
    return rows


def changed_cell_ranges(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    tab_name: str,
    headers: list[str],
    records: dict[str, dict[str, Any]],
    changes: list[dict[str, Any]],
) -> list[dict[str, int]]:
    if not changes:
        return []

    metadata = spreadsheet_metadata(credentials, spreadsheet_id)
    sheet = sheet_metadata_by_title(metadata)[tab_name]
    sheet_id = sheet["properties"]["sheetId"]
    sorted_dates = sorted(records)
    date_to_row = {date_key: idx + 1 for idx, date_key in enumerate(sorted_dates)}
    header_to_col = {header: idx for idx, header in enumerate(headers)}
    ranges = []
    for change in changes:
        col_idx = header_to_col.get(change["column"])
        row_idx = date_to_row.get(change["date"])
        if col_idx is None or row_idx is None:
            continue
        ranges.append(
            {
                "sheetId": sheet_id,
                "startRowIndex": row_idx,
                "endRowIndex": row_idx + 1,
                "startColumnIndex": col_idx,
                "endColumnIndex": col_idx + 1,
            }
        )
    return ranges


def write_updates(
    service_account_file: str | Path,
    updates: list[dict[str, Any]],
    cadence: str,
    spreadsheet_id: str | None = None,
    title: str = "Scorecard",
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], str, str]:
    credentials = make_credentials(service_account_file)
    resolved_id = resolve_spreadsheet_id(credentials, spreadsheet_id, title)
    target_tabs = {
        data_sheet_name(cadence, update["sheet"])
        for update in updates
    }
    metadata = ensure_tabs(credentials, resolved_id, target_tabs)
    spreadsheet_url = metadata.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{resolved_id}")

    changes: list[dict[str, Any]] = []
    updates_by_tab: dict[str, list[dict[str, Any]]] = {}
    for update in updates:
        updates_by_tab.setdefault(data_sheet_name(cadence, update["sheet"]), []).append(update)

    for tab_name, tab_updates in updates_by_tab.items():
        date_column = tab_updates[0]["date_column"]
        existing_rows = get_values(credentials, resolved_id, tab_name)
        headers, records = parse_existing_table(existing_rows, date_column)
        tab_changed = False
        tab_changes: list[dict[str, Any]] = []
        tab_automation_cells: list[dict[str, Any]] = []
        normalized_headers = ensure_expected_headers(tab_name, headers)
        if normalized_headers != headers:
            headers = normalized_headers
            tab_changed = True

        touched_dates: set[str] = set()
        for update in tab_updates:
            date_key = normalize_date(update["date"]).isoformat()
            touched_dates.add(date_key)
            record_values = records.setdefault(date_key, {})
            for header, value in update.get("values", {}).items():
                if header not in headers:
                    headers.append(header)
                value = normalize_scorecard_value(header, serializable_value(value))
                tab_automation_cells.append(
                    {"sheet": tab_name, "date": date_key, "column": header}
                )
                if values_equivalent(record_values.get(header), value):
                    continue
                change = {
                    "sheet": tab_name,
                    "date": date_key,
                    "column": header,
                    "before": record_values.get(header),
                    "after": value,
                }
                changes.append(change)
                tab_changes.append(change)
                record_values[header] = value
                tab_changed = True

        formula_columns = {
            header
            for update in tab_updates
            for header in update.get("formula_columns", [])
            if header in headers
        }
        if formula_columns:
            for date_key in touched_dates:
                for header in formula_columns:
                    tab_automation_cells.append(
                        {"sheet": tab_name, "date": date_key, "column": header}
                    )
            before_formula_values = {
                date_key: {
                    header: records[date_key].get(header, "")
                    for header in formula_columns
                }
                for date_key in records
            }
            normalize_formula_owned_cells(
                headers,
                records,
                formula_columns,
                touched_dates,
            )
            for date_key in sorted(records):
                if date_key not in touched_dates:
                    continue
                for header in sorted(formula_columns):
                    before = before_formula_values[date_key][header]
                    after = normalize_scorecard_value(
                        header,
                        records[date_key].get(header, ""),
                    )
                    records[date_key][header] = after
                    if values_equivalent(after, before):
                        continue
                    change = {
                        "sheet": tab_name,
                        "date": date_key,
                        "column": header,
                        "before": before,
                        "after": after,
                    }
                    changes.append(change)
                    tab_changes.append(change)
                    tab_changed = True

        if tab_changed and not dry_run:
            clear_values(credentials, resolved_id, tab_name)
            rows = build_rows(headers, records)
            put_values(credentials, resolved_id, tab_name, rows)
            ensure_table(credentials, resolved_id, tab_name, headers, len(rows))

        if not dry_run:
            format_scorecard_columns(
                credentials,
                resolved_id,
                tab_name,
                headers,
                len(records) + 1,
            )

        if not dry_run and tab_automation_cells:
            format_automated_cells(
                credentials,
                resolved_id,
                changed_cell_ranges(
                    credentials,
                    resolved_id,
                    tab_name,
                    headers,
                    records,
                    tab_automation_cells,
                ),
            )

    return changes, resolved_id, spreadsheet_url














