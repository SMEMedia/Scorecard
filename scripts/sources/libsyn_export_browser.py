from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from time import sleep
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources" / "monthly" / "libsyn.json"


class BrowserExportError(RuntimeError):
    pass


def load_config(path: str | Path | None) -> tuple[dict[str, Any], Path]:
    config_path = Path(path or DEFAULT_CONFIG)
    with open(config_path, "r", encoding="utf-8") as handle:
        return json.load(handle), config_path


def load_credentials(config: dict[str, Any]) -> dict[str, str]:
    credentials_file = Path(config.get("credentials_file", ""))
    if not credentials_file.exists():
        raise BrowserExportError(f"Libsyn credentials file does not exist: {credentials_file}")
    raw = credentials_file.read_text(encoding="utf-8").strip()
    if not raw:
        raise BrowserExportError(f"Libsyn credentials file is empty: {credentials_file}")
    credentials = json.loads(raw)
    email = credentials.get("email")
    password = credentials.get("password")
    if not email or not password:
        raise BrowserExportError("Libsyn credentials file needs email and password.")
    return {"email": email, "password": password}


def click_visible_text(page: Any, text: str, timeout: int = 15000) -> None:
    candidates = [
        page.get_by_role("button", name=text),
        page.get_by_text(text, exact=True),
        page.locator(f"text={text}"),
    ]
    for candidate in candidates:
        try:
            candidate.first.click(timeout=timeout)
            return
        except PlaywrightTimeoutError:
            continue
    raise BrowserExportError(
        f"Could not click visible Libsyn control: {text}. "
        f"Current URL: {page.url}. Page title: {page.title()}."
    )


def visible_text(page: Any, text: str, timeout: int = 5000) -> bool:
    """Return whether text is visible without relying on Libsyn's ARIA roles."""
    try:
        return page.get_by_text(text, exact=True).first.is_visible(timeout=timeout)
    except PlaywrightTimeoutError:
        return False


def fill_login_if_needed(page: Any, credentials: dict[str, str]) -> None:
    email_selectors = [
        "input[type='email']",
        "input[name='email']",
        "input[name='username']",
        "input[name='user']",
        "input[name='login']",
        "input[name='login_email']",
        "input[name='login_username']",
        "input[id*='login' i]",
        "input[id*='email' i]",
        "input[id*='user' i]",
    ]
    password_selector = "input[type='password'], input[name='password'], input[id*='password' i]"

    email_field = None
    for selector in email_selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=2500):
                email_field = locator
                break
        except PlaywrightTimeoutError:
            continue

    password_field = page.locator(password_selector).first
    try:
        password_visible = password_field.is_visible(timeout=2500)
    except PlaywrightTimeoutError:
        password_visible = False

    if email_field is None or not password_visible:
        return

    email_field.fill(credentials["email"])
    password_field.fill(credentials["password"])
    try:
        page.get_by_role("button", name="Log In").click(timeout=5000)
    except PlaywrightTimeoutError:
        try:
            page.get_by_role("button", name="Login").click(timeout=5000)
        except PlaywrightTimeoutError:
            password_field.press("Enter")
    wait_for_network_quiet(page, timeout=20000)


def is_login_page(page: Any) -> bool:
    if "auth/authorize" in page.url or "login" in page.url.lower():
        return True
    try:
        return page.locator("input[type='password']").first.is_visible(timeout=1000)
    except PlaywrightTimeoutError:
        return False


def wait_for_login_or_stats(
    page: Any,
    credentials: dict[str, str],
    stats_url: str,
    login_wait_seconds: int,
    headless: bool,
) -> None:
    fill_login_if_needed(page, credentials)
    if visible_text(page, "Download Report"):
        return
    if not is_login_page(page):
        return

    if not headless and login_wait_seconds > 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "needs_interaction": True,
                    "message": (
                        "Libsyn is asking for login or verification. "
                        "Complete it in the browser window; automation will continue afterward."
                    ),
                    "current_url": page.url,
                    "page_title": page.title(),
                    "wait_seconds": login_wait_seconds,
                }
            ),
            file=sys.stderr,
            flush=True,
        )
        sleep(login_wait_seconds)
        wait_for_network_quiet(page)
        if page.url != stats_url:
            page.goto(stats_url, wait_until="domcontentloaded", timeout=90000)
            wait_for_network_quiet(page)
        return

    raise BrowserExportError(
        "Libsyn login is required before exporting. "
        f"Current URL: {page.url}. Page title: {page.title()}."
    )


def choose_dropdown_value(page: Any, field_index: int, value: str) -> None:
    controls = page.locator(".libsyn-select__control")
    if controls.count() > field_index:
        controls.nth(field_index).click(timeout=15000)
    else:
        page.locator("text=Select...").nth(field_index).click(timeout=15000, force=True)
    try:
        page.get_by_text(value, exact=True).first.click(timeout=5000)
    except PlaywrightTimeoutError:
        page.keyboard.type(value)
        page.keyboard.press("Enter")


def wait_for_network_quiet(page: Any, timeout: int = 15000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeoutError:
        return


def ensure_stats_page(page: Any, stats_url: str) -> None:
    if visible_text(page, "Download Report"):
        return
    try:
        page.locator("#navbar_stats").first.click(timeout=5000)
    except PlaywrightTimeoutError:
        try:
            page.get_by_role("link", name="stats", exact=True).first.click(timeout=5000)
        except PlaywrightTimeoutError:
            page.goto(stats_url, wait_until="domcontentloaded", timeout=90000)
            wait_for_network_quiet(page)
            return
    wait_for_network_quiet(page)


def export_report(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    credentials = load_credentials(config)
    stats_url = config.get("browser_stats_url") or config.get("export_url") or "https://five.libsyn.com/show/stats"
    profile_dir = Path(config.get("browser_profile_dir") or PROJECT_ROOT / "config" / "libsyn_browser_profile")
    downloads_dir = Path(config.get("browser_downloads_dir") or PROJECT_ROOT / "outputs" / "libsyn")
    downloads_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    date_range_label = config.get("browser_export_date_range", "Last 90 Days")
    file_type_label = config.get("browser_export_file_type", "CSV")
    headless = bool(config.get("browser_headless", False))
    slow_mo = int(config.get("browser_slow_mo_ms", 75 if not headless else 0))
    login_wait_seconds = int(config.get("browser_login_wait_seconds", 120))
    stats_ready_timeout_ms = int(config.get("browser_stats_ready_timeout_ms", 90000))

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = downloads_dir / f"libsyn-downloads-{timestamp}.csv"

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            accept_downloads=True,
            headless=headless,
            slow_mo=slow_mo,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(stats_url, wait_until="domcontentloaded", timeout=90000)
        wait_for_login_or_stats(page, credentials, stats_url, login_wait_seconds, headless)
        if page.url != stats_url:
            page.goto(stats_url, wait_until="domcontentloaded", timeout=90000)
            wait_for_network_quiet(page)
            wait_for_login_or_stats(page, credentials, stats_url, login_wait_seconds, headless)
        else:
            wait_for_network_quiet(page)
        ensure_stats_page(page, stats_url)

        try:
            page.get_by_text("Download Report", exact=True).first.wait_for(
                state="visible",
                timeout=stats_ready_timeout_ms,
            )
        except PlaywrightTimeoutError as error:
            raise BrowserExportError(
                "Libsyn stats page loaded, but Download Report did not become visible "
                f"within {stats_ready_timeout_ms // 1000} seconds. "
                f"Current URL: {page.url}. Page title: {page.title()}."
            ) from error
        click_visible_text(page, "Download Report")
        page.get_by_text("Stats Export", exact=True).wait_for(timeout=30000)

        total_downloads = page.get_by_label("Total Downloads")
        try:
            if total_downloads.is_visible(timeout=3000) and not total_downloads.is_checked():
                total_downloads.check()
        except PlaywrightTimeoutError:
            click_visible_text(page, "Total Downloads")

        choose_dropdown_value(page, 0, date_range_label)
        choose_dropdown_value(page, 1, file_type_label)

        with page.expect_download(timeout=120000) as download_info:
            click_visible_text(page, "Export")
        download = download_info.value
        download.save_as(str(output_path))
        context.close()

    return {
        "ok": True,
        "path": str(output_path),
        "notes": [
            f"Loaded Libsyn config from {config_path}.",
            f"Downloaded Libsyn export through Playwright using {date_range_label} / {file_type_label}.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a Libsyn stats export through Playwright.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        config, config_path = load_config(args.config)
        result = export_report(config, config_path)
    except Exception as error:
        result = {"ok": False, "error": str(error)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
