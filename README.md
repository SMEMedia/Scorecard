# Scorecard Automation

This project automates Monthly and Weekly Scorecard source values into the shared Google Sheet `Scorecard`.

## Quick Start

Use the single project command for routine work:

```powershell
# Preview or run the monthly update.
python scorecard.py monthly --dry-run
python scorecard.py monthly

# Preview or run the weekly update.
python scorecard.py weekly --dry-run
python scorecard.py weekly

# Compare Excel sources with Google Sheets.
python scorecard.py compare --date 2026-08-15

# List all supported commands.
python scorecard.py --help
```

The older files under `scripts/commands/` remain supported as compatibility entry points for existing scheduled tasks.

## Project Layout

```text
scorecard.py          One command for routine monthly, weekly, source, and audit runs
config/scorecard.json Shared Google Sheet and Excel audit paths
config/sources/       Monthly, weekly, shared, and optional source settings
config/secrets/       Local credentials (ignored by git)
config/state/         OAuth caches, snapshots, cookies, and browser state (ignored by git)
config/examples/      Shareable configuration templates
scripts/sources/      External API integrations
scripts/pipelines/    Source-record to Scorecard-column mappings
scripts/lib/          Shared Google Sheets writer and calculations
scripts/commands/     Backward-compatible command entry points
scripts/tools/        Diagnostics, repairs, and discrepancy auditing
scripts/dashboards/   Optional dashboard applications
```

## Media Performance Dashboard

Run the comprehensive Streamlit dashboard from the project root:

```powershell
streamlit run scripts\dashboards\media_performance_dashboard.py
```

It reads the four reporting tabs in the shared Google Scorecard and provides monthly
and weekly executive KPIs, period-over-period changes, cross-channel trends, media
detail, engagement reporting, and completeness checks. By default it uses the
spreadsheet ID and service-account file in `config/scorecard.json`.

For local use, the dashboard reads the service-account file configured in
`config/scorecard.json`. For Streamlit Community Cloud, store the service-account
fields directly in the app's Secrets settings instead of committing a credential
file or using a local file path:

```toml
spreadsheet_id = "your-google-sheet-id"

[google_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = """-----BEGIN PRIVATE KEY-----
your-private-key
-----END PRIVATE KEY-----
"""
client_email = "service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "your-client-certificate-url"
universe_domain = "googleapis.com"
```

## Google Sheet Target

The shared Google Sheet target is configured in `config/scorecard.json`.

- Google Sheet: `Scorecard`
- Spreadsheet ID: `1byunytq2svgs56Sp4xwogYEhQOAv2xHw5HTELfzBRi4`

## Monthly Scorecard Source Map

### `SME Media Data`

| Columns | Source |
| --- | --- |
| B-J | GA4 |
| K-N | Walsworth thermostats |
| N-P | Personify |
| Q-U | GA4 |
| V | Google Play Console + App Store |
| X | Libsyn |
| Y | YouTube |
| Z | GA4 (`AM Web Podcast Plays`) |
| AB | YouTube |
| AC-AH | GA4 + Google Search Console |
| AI-AP | HubSpot |
| AS | Meta Social APIs |
| AT | YouTube |
| AU | LinkedIn Analytics |
| AV | X API |
| AW | Meta Social APIs |

Notes:

- Column `N` appears in both the Walsworth thermostats range (`K-N`) and Personify range (`N-P`). We should confirm ownership before implementing those columns.
- Native social API ownership replaces DataBox for follower values: Meta owns `Facebook Followers` and `Instagram Followers`, X owns `X Followers`, LinkedIn owns `LinkedIn Followers`, and YouTube owns `YouTube Subscribers`.

### `SME Media Data (Detail)`

| Columns | Source |
| --- | --- |
| B-K | GA4 |
| L-Y | LinkedIn Analytics |

### `SME Media Engagement Metrics`

| Columns | Source |
| --- | --- |
| B-K | GA4 |
| L-N | YouTube |

## Weekly Scorecard Framework

Weekly automation scaffolding has started. Weekly rows use Saturday `Week Ending` dates. By default, weekly sources should target the latest completed Saturday. For example, on July 8, 2026, the target Weekly scorecard date is `2026-07-04`.

Current Weekly table mapping:

| Sheet | Table | Date Column |
| --- | --- | --- |
| `SME Media Data` | `Table1` | `Week Ending` |

Current known Weekly source ownership, pending final validation:

| Sheet | Columns / Metrics | Likely Source |
| --- | --- | --- |
| `SME Media Data` | AM web/app traffic metrics | GA4, implemented |
| `SME Media Data` | Podcast Downloads | Libsyn, implemented |
| `SME Media Data` | AM Web Podcast Plays | GA4 `eventCount` where `eventName = audio` and `audio_player_action = play`, implemented |
| `SME Media Data` | YouTube Podcast Plays | YouTube, implemented |
| `SME Media Data` | YouTube Video Plays | Formula-owned, not written directly |
| `SME Media Data` | GA4 Search Clicks, Google Search Console Search Clicks, GA4 Search Impressions, Google Search Console Search Impressions, Ave Search Position, Search CTR | GA4 + Google Search Console, implemented |
| `SME Media Data` | Email delivery/open/click metrics | HubSpot, implemented but blocked until the token has `content` scope |
| `SME Media Data` | IO and Pipeline metrics | Source to confirm |

Current formula-owned Weekly columns intentionally not written:

| Sheet | Columns |
| --- | --- |
| `SME Media Data` | `AM New User %%`, `AM Return User %%`, `AM Sessions / User`, `AM Page Views / Session`, `Podcast Total`, `YouTube Video Plays`, `Email Open Rate`, `Email CTR`, `Email Click to Open Rate` |

The full Weekly IO/Pipeline block—from `New IOs (Count)` through `Pipeline Total (Tv)`—is manual. Automation neither writes nor applies green automation fill to those columns.

Weekly commands:

```powershell
python scripts\commands\run_weekly_sources.py
python scripts\commands\run_weekly_scorecard.py --dry-run
python scripts\commands\run_weekly_scorecard.py
```

The Weekly command framework now returns records for GA4, Libsyn, YouTube, and Google Search Console. HubSpot weekly records use the same email histogram endpoint as Monthly, but still require the HubSpot private app token to have the `content` scope. Walsworth, Personify/Fonteva, IO, and Pipeline are still pending access or final source mapping.

## Automation Data Layer

Routine monthly and weekly scorecard commands write source values to the shared Google Sheet `Scorecard`.

Google Sheet tables:

| Sheet | Feeds |
| --- | --- |
| `Monthly Media Data` | Monthly `SME Media Data` value columns |
| `Monthly Media Detail` | Monthly `SME Media Data (Detail)` value columns |
| `Monthly Engagement` | Monthly `SME Media Engagement Metrics` value columns |
| `Weekly Media Data` | Weekly `SME Media Data` value columns |

All four tabs should be Google Sheets tables. The Sheets writer creates missing tables and updates existing table ranges/column definitions after writes, so source runs should not strip table structure.

Cells changed by update commands are filled pale green. Seeded historical values and blanks are not highlighted.

## Snapshot Mode

The Monthly and Weekly write commands run in snapshot mode by default. Source records are keyed by source, report, sheet, date column, and scorecard date. On the first saved run for a period, the command writes those records to:

```text
config/state/scorecard_snapshots.json
```

Later saved runs for the same period reuse the saved snapshot instead of replacing period values with newer API responses. This keeps month/week rows stable after they are captured. Dry runs read existing snapshots but do not create new ones.

To intentionally replace saved period values after fixing a source mapping or bad capture:

```powershell
python scripts\commands\run_monthly_scorecard.py --refresh-snapshots
python scripts\commands\run_weekly_scorecard.py --refresh-snapshots
```

Normal runs write only to the shared Google Sheet.

## Framework Logic

The framework is split into three layers:

1. Source modules fetch data from external systems and return normalized records.
2. Pipeline modules map those records to scorecard sheet/date/column updates and filter out formula-owned columns.
3. `scripts/lib/google_sheets_data.py` writes those updates to the shared Google Sheet `Scorecard`.

The source modules do not write directly to the output target. Routine data writes go through `scripts/lib/google_sheets_data.py`.

### Source Modules

- `scripts/sources/ga4.py`
- `scripts/sources/walsworth_thermostats.py`
- `scripts/sources/personify.py`
- `scripts/sources/app_stores.py`
- `scripts/sources/libsyn.py`
- `scripts/sources/youtube.py`
- `scripts/sources/search_console.py`
- `scripts/sources/hubspot.py`
- `scripts/sources/databox.py`
- `scripts/sources/meta_social.py`
- `scripts/sources/x_social.py`
- `scripts/sources/linkedin_analytics.py`
- `scripts/sources/weekly_utils.py`

Current source status:

- GA4 is implemented for Monthly source extraction.
- YouTube is implemented for channel-level monthly engagement metrics and current subscriber count.
- Libsyn is implemented for monthly podcast downloads using a Playwright-driven Libsyn Five CSV export.
- GA4 is implemented for Monthly and Weekly `GA4 Search Clicks` and `GA4 Search Impressions` by grouping `eventCount` by `searchTerm`; Google Search Console is implemented for `Google Search Console Search Clicks`, `Google Search Console Search Impressions`, `Ave Search Position`, and `Search CTR`.
- Google Play Console is scaffolded but waiting on Play Console export access.
- HubSpot is partially implemented but waiting on the required token scopes.
- Meta Social APIs are implemented for Facebook and Instagram follower snapshots. X API remains scaffolded pending final credentials and month-end strategy.
- DataBox remains available for API validation/discovery only; it is not part of the monthly write pipeline.
- All other source modules are placeholders.
- `scripts/commands/run_monthly_sources.py` runs the Monthly source modules and prints their status/results. It does not write to the Google Sheet.
- `scripts/commands/run_weekly_sources.py` runs the Weekly source modules and prints their status/results. It does not write to the Google Sheet.

### Writer Scripts

- `scripts/commands/run_monthly_scorecard.py` is the main monthly entry point. It pulls every monthly source that exists and writes returned value updates to the shared Google Sheet.
- `scripts/commands/run_weekly_scorecard.py` is the main Weekly entry point. It pulls every Weekly source that exists and writes returned value updates to the shared Google Sheet.
- `scripts/commands/write_ga4_monthly.py` is a GA4-only Google Sheet writer for source-specific testing.
- `scripts/tools/compare_scorecards.py` is an audit-only command that compares the configured Excel source workbooks with the shared Google Sheet and replaces the `Discrepancies` tab with results sorted by severity. It does not participate in monthly or weekly updates.

Discrepancy comparison examples:

```powershell
# Compare every available source row and update the Discrepancies tab.
python scripts\tools\compare_scorecards.py

# Compare one exact date.
python scripts\tools\compare_scorecards.py --date 2026-07-01

# Compare an inclusive date range.
python scripts\tools\compare_scorecards.py --start-date 2026-06-01 --end-date 2026-07-31

# Preview without changing Google Sheets.
python scripts\tools\compare_scorecards.py --date 2026-07-01 --dry-run
```
- `scripts/demos/demo_write_scorecards.py` is only a throwaway/demo script from the first write test. Production logic should not depend on it.

Important date convention:

- Monthly date labels such as `2026-06-01` mean the month of June 2026.
- They do not mean that data was entered on June 1 for the prior month.
- Monthly automation should target the latest completed month by default. On July 7, 2026, that means June 2026, labeled `2026-06-01`.

### Current GA4 Write Flow

`scripts/commands/run_monthly_scorecard.py`:

1. Calls all monthly source modules.
2. Prints status and notes for each source.
3. Collects records returned by implemented sources.
4. Maps each record to the correct Monthly Google Sheet table through `scripts/pipelines/monthly_pipeline.py`.
5. Filters out formula-owned columns.
6. Calls `scripts/lib/google_sheets_data.py` to write changes to the shared Google Sheet.

Right now, GA4 is the only monthly source returning records. Other sources are included in the run and report that they are not implemented yet.

Current Monthly table mapping:

| Sheet | Table |
| --- | --- |
| `SME Media Data` | `Table1` |
| `SME Media Data (Detail)` | `Table14` |
| `SME Media Engagement Metrics` | `Table147` |

Current formula-owned GA4 columns intentionally not written:

| Sheet | Columns |
| --- | --- |
| `SME Media Data` | `AM New User %%`, `AM Return User %%`, `AM Sessions / User`, `AM Page Views / Session`, `App Return Users` |
| `SME Media Engagement Metrics` | `AM.org Total Users (#)`, `AM.org Return Users (#)`, `AM.org Return Users (%)`, `Sessions `, `Sessions Per User` |

These columns are either formulas in the scorecard model or depend on other source modules that are not implemented yet.

The `SME Media Data (Detail)` GA4 traffic-source columns use GA4's custom
channel group dimension `sessionCustomChannelGroup:8166437547`, shown in the GA4
exploration UI as `Session Modified GA4 Default`. They do not use raw
`sessionMedium`. `Organic Video` and `Paid Video` are summed into the existing
`Session Medium (Video)` scorecard column.

`SME Media Data / AM Return Users` is pulled from a separate GA4 report using
the `newVsReturning` dimension where the dimension value is `returning` and the
metric is `totalUsers`. It is not calculated as `AM Users - AM New Users`.

### Current HubSpot Flow

`scripts/sources/hubspot.py` is configured to use the Marketing Email statistics histogram endpoint:

```text
GET /marketing/emails/2026-03/statistics/histogram
```

Query parameters:

- `interval=MONTH`
- `startTimestamp`
- `endTimestamp`

The endpoint returns monthly email aggregations. The current mapping is:

| HubSpot field | Scorecard column |
| --- | --- |
| HubSpot list `274` size | `Email Subscribers` |
| Folder email `aggregations.counters.delivered` | `Emails Delivered` |
| Folder email `OPEN` events where `filteredEvent = false` | `Email Opens` |
| Folder email `CLICK` events where `filteredEvent = false` | `Email Clicks` |
| `aggregations.ratios.openratio` | `Email Open Rate` |
| `aggregations.ratios.clickratio` | `Email CTR` |
| `aggregations.ratios.clicktoopenratio` | `Email Click to Open Rate` |

The scorecard owns the rate formulas, so the pipeline filters out `Email Open Rate`, `Email CTR`, and `Email Click to Open Rate` before writing.

`Email Starts` is not written by HubSpot. It is Personify-owned and should stay out of the HubSpot histogram mapping.

Manufacturing Weekly email metrics are pulled from HubSpot folders named
`<Month YYYY>`, such as `June 2026` or `July 2026`, under the Marketing Email
folder structure. The automation resolves the folder ID dynamically from the
scorecard date. It includes sent emails, excludes names containing `(Clone)`,
and excludes names whose embedded `m/d/yy` date is outside the report date
range. Weekly reports check every month folder touched by the week, so a week
that crosses from June into July can include both folder IDs. Total opens and
clicks come from the legacy HubSpot email events endpoint because the histogram
endpoint returns unique opens/clicks.

HubSpot token setup:

- Token path: `config/secrets/hubspot_private_app_token.txt`
- Config path: `config/sources/monthly/hubspot.json`
- Required private app scope for the histogram endpoint: `content`

Additional scopes may still be needed later if subscriber counts or other email fields move to a different endpoint.

### Current App Store / Google Play Flow

`scripts/sources/app_stores.py` scaffolds the app-download source for column `V` (`Monthly App Downloads`). It should only write values that match App Analytics / console download totals.

Google Play Console monthly statistics are exported as CSV files in a private Google Cloud Storage bucket for the Play Developer account. The source uses:

```text
https://www.googleapis.com/auth/devstorage.read_only
```

Current config:

- `config/sources/optional/google_play.json`
- Google Play service account key: `config/secrets/google_service_account.json`
- App Store Connect private key: `config/secrets/AuthKey_WVG978J68Z.p8`

Google Play currently uses service-account auth:

```json
"auth_mode": "service_account"
```

Required Google Play config values before that portion can run:

- `google_play.bucket_id`: the Play Console Cloud Storage bucket ID exactly as shown in Play Console, without the `gs://` prefix
- `google_play.package_name`: the Android app package name

Default report object pattern:

```text
stats/installs/installs_{package_name}_{year_month}_country.csv
```

Default metric:

```text
Daily User Installs
```

Google Play Console permission changes can take a long time to reach the Play-managed
Cloud Storage bucket. If the service account has `View app information and download
bulk reports (read-only)` but the script still returns `storage.objects.get` or
`storage.objects.list` denied, wait up to 24 hours before changing the integration.

App Store Connect is filtered to the Advanced Manufacturing app only:

```text
Apple Identifier: 6494275046
SKU: com.smemedia.ios
Bundle ID: com.smemedia.ios
```

The unfiltered Sales and Trends report summed multiple SME apps and produced the incorrect `178`. With the Advanced Manufacturing filters, June maps to `5`, matching the App Analytics Total Downloads screenshot. The App Analytics report-request API was also probed, but the current API key cannot create analytics report requests.

Required App Store Connect config values:

- `app_store.issuer_id`: the App Store Connect API issuer ID.
- `app_store.key_id`: the App Store Connect API key ID.
- `app_store.private_key_file`: the App Store Connect `.p8` key.
- `app_store.apple_ids`: must include only Advanced Manufacturing, currently `6494275046`.
- `app_store.skus`: must include only Advanced Manufacturing, currently `com.smemedia.ios`.

Once the correct Apple and Google Play download metrics are available, values should be summed and written to:

```text
SME Media Data / Monthly App Downloads
```

### Current YouTube Flow

`scripts/sources/youtube.py` uses OAuth and the official YouTube APIs.

Current config:

- `config/sources/monthly/youtube.json`
- OAuth client secret: `config/secrets/google_oauth_client_secret.json`
- OAuth token cache: `config/state/youtube_oauth_token.json`
- Optional service account key: `config/secrets/google_service_account.json`

Required OAuth scopes:

- `https://www.googleapis.com/auth/youtube.readonly`
- `https://www.googleapis.com/auth/yt-analytics.readonly`

The OAuth client project must also have these APIs enabled:

- YouTube Analytics API
- YouTube Data API v3

Service-account auth is scaffolded with `auth_mode = service_account`, but Google's YouTube Data API docs state that service accounts are not supported for YouTube channel/user data and may fail with `NoLinkedYouTubeAccount`. OAuth remains the working default unless a service-account test succeeds.

The YouTube Analytics API is used for channel-level monthly metrics:

```text
GET https://youtubeanalytics.googleapis.com/v2/reports
```

Current monthly channel mapping:

| YouTube Analytics metric | Scorecard column |
| --- | --- |
| `views` | `SME Media Engagement Metrics / Videos Views*` |
| `averageViewDuration` | `SME Media Engagement Metrics / Avg. View Duration*` |
| `estimatedMinutesWatched` | `SME Media Engagement Metrics / Watch Time (Hours)*` |
| `views` with podcast playlist filter | `SME Media Data / YouTube Podcast Plays` |

`averageViewDuration` is returned by YouTube in seconds. The scorecard displays these values as `m:ss`, so the automation stores the value as a time-like value where the hour component represents minutes and the minute component represents seconds. For example, 80 seconds is written as `1:20`. `estimatedMinutesWatched` is converted to hours.

The YouTube Data API can read the current channel subscriber count:

```text
GET https://www.googleapis.com/youtube/v3/channels?part=statistics&mine=true
```

Subscriber mapping:

```text
SME Media Data / YouTube Subscribers
```

Important limitation: the Data API returns the channel's current subscriber count, not the count as of the scorecard month end. To prevent historical rows from changing on every rerun, subscriber values now use a local snapshot file:

```text
config/state/youtube_subscribers.json
```

When `monthly_channel_subscribers` runs, it first checks for the scorecard month in that file. If a saved value exists, it reuses the saved value. If no saved value exists, it captures the current channel subscriber count once, stores it under the scorecard month, and returns that value. For the most accurate month-end numbers, run the automation immediately after month close or manually correct the snapshot value before writing.

Podcast plays are enabled in `config/sources/monthly/youtube.json` using playlist ID `PLEMmsgg0GMzCJZnBjaIyMBUPVx9hT0Ft0` for `Advanced Manufacturing Now`. `SME Media Data / YouTube Video Plays` is treated as a formula-owned column and is not written directly by the automation.

Run YouTube only:

```powershell
python scripts\sources\youtube.py
```

Run the live YouTube content dashboard:

```powershell
streamlit run scripts\dashboards\youtube_content_dashboard.py
```

The dashboard uses the same OAuth setup as `scripts/sources/youtube.py`, fetches video-level totals, classifies videos with YouTube Data API metadata, and then pulls daily YouTube Analytics rows filtered to each content-type group's video IDs. Podcasts come from the podcast playlist configured in `config/sources/monthly/youtube.json`, so podcast videos are not double-counted as ordinary videos.

### Current Native Social Flow

Follower totals are moving to native platform APIs instead of DataBox.

Current native social ownership:

| Scorecard column | Source module |
| --- | --- |
| `Facebook Followers` | `scripts/sources/meta_social.py` |
| `Instagram Followers` | `scripts/sources/meta_social.py` |
| `X Followers` | `scripts/sources/x_social.py` |
| `LinkedIn Followers` | `scripts/sources/linkedin_analytics.py` |
| `YouTube Subscribers` | `scripts/sources/youtube.py` |

Important month-end caveat:

- Follower-count API fields are often current snapshots, not historical month-end values.
- Meta follower values use current snapshots assigned to the latest completed month and are frozen by the scorecard snapshot cache after the first successful monthly run.
- Run the monthly updater promptly after month end so the saved snapshot closely represents the intended month-end count.

Meta config:

- `config/sources/monthly/meta.json`
- Local secrets file: `config/secrets/meta.toml` (excluded from version control)

Meta currently automates:

- Facebook Page `followers_count`
- Instagram Business `followers_count`

X config:

- `config/sources/monthly/x.json`
- Bearer token file: `config/secrets/x_bearer_token.txt`

X currently scaffolds:

- User lookup `public_metrics.followers_count`

Run native social sources:

```powershell
python scripts\sources\meta_social.py
python scripts\sources\x_social.py
```

### Current Libsyn Flow

`scripts/sources/libsyn.py` uses a Playwright browser helper to automate the Libsyn Five stats export and calculate total podcast downloads. The browser helper opens Libsyn, signs in with the stored credentials when needed, clicks `Download Report`, chooses `Total Downloads`, exports `Last 90 Days` as `CSV`, and then the source sums the daily `Unique Downloads` rows that fall inside the scorecard period.

Libsyn may deliver that export either as a plain CSV or as a ZIP archive carrying a `.csv` filename. The source detects both formats and selects the summary CSV rather than the separate by-episode report.

Libsyn exports include separate `Daily Downloads`, `Weekly Downloads`, and `Monthly Downloads` sections. The scorecard source intentionally sums only rows from the `Daily Downloads` section so weekly/monthly summary rows are not double-counted.

Current config:

- `config/sources/monthly/libsyn.json`
- Credentials file: `config/secrets/libsyn_credentials.json`
- Cookie cache: `config/state/libsyn_cookie.txt`
- Browser profile: `config/state/libsyn_browser_profile`
- Browser exports: `outputs/libsyn`
- Optional local CSV export path: `csv_file`

Credential file shape:

```json
{
  "email": "your@email.com",
  "password": "your password"
}
```

Important config values:

- `browser_export_enabled`: `true` uses Playwright to fetch the export automatically.
- `browser_headless`: `false` opens a visible browser; use this while setting up or if Libsyn asks for verification.
- `browser_subprocess_timeout_seconds`: bounds the full browser export so a stalled Libsyn page cannot hang a scorecard run indefinitely.
- `browser_export_date_range`: currently `Last 90 Days`, which includes the latest completed month.
- `browser_export_file_type`: currently `CSV`.
- `browser_cache_enabled`: reuses the newest export if its daily rows fully cover the target month.
- `data_section`: currently `Daily Downloads`; this prevents weekly/monthly export sections from being counted too.
- `metric_column`: currently `Unique Downloads`, matching the live/manual scorecard convention.
- Weekly Libsyn uses the scorecard's Saturday `Week Ending` date as the row label but sums Sunday through Friday by setting `default_date_range.end_offset_days` to `-1`.
- Weekly Libsyn opens a visible browser so login or verification can be completed when needed. Browser status is shown in the weekly command, and the full export remains bounded by `browser_subprocess_timeout_seconds` so it cannot wait indefinitely.
- `csv_file`: optional local path to a downloaded Libsyn CSV export for debugging or fallback.
- `scorecard_column`: the exact column header for column `X` in `SME Media Data`.

The first browser run may require a visible login or verification step. Playwright stores that browser session in `config/state/libsyn_browser_profile`, which is ignored by git. Once the profile is signed in reliably, `browser_headless` can be changed to `true`.

When browser cache is enabled, the source keeps one usable CSV in `outputs/libsyn`. If the newest cached CSV does not cover the scorecard month, it downloads a fresh export and removes older cached exports.

Run Libsyn diagnostics without writing:

```powershell
python scripts\sources\libsyn.py --diagnose
```

Run Libsyn monthly source:

```powershell
python scripts\sources\libsyn.py
```

The verified July 8, 2026 source run returned the June 2026 scorecard record:

```json
{
  "date": "2026-06-01",
  "values": {
    "Podcast Downloads": 4519
  }
}
```

### Current DataBox Flow

`scripts/sources/databox.py` is scaffolded for read-only API validation and discovery. It is no longer configured as a monthly scorecard writer because the Databox v1 public API docs expose account, data-source, dataset, and ingestion endpoints, but not an official existing-metric history read endpoint.

Current config:

- `config/sources/optional/databox.json`
- API key file: `config/secrets/databox_api_key.txt`

Authentication uses the Databox `x-api-key` header.

Run Databox standalone source check:

```powershell
python scripts\sources\databox.py
```

Run Databox read-only account/data-source discovery after the API key file is populated:

```powershell
python scripts\sources\databox.py --discover
```

Dataset listing is skipped by default to avoid excessive API calls. To inspect datasets for specific data sources, add their IDs to `config/sources/optional/databox.json` under `discovery.dataset_source_ids`, then run:

```powershell
python scripts\sources\databox.py --discover --include-datasets
```

## GA4 Setup

GA4 is the first source integration being implemented. It uses the official Google Analytics Data API client.

### OAuth

The current config uses OAuth because the signed-in user account can be granted access to GA4 properties more easily than a service account.

Expected OAuth files:

- Client secret: `config/secrets/google_oauth_client_secret.json`
- Token cache: `config/state/ga4_oauth_token.json`

The token cache is created after the first successful browser login. Both files are ignored by `.gitignore`.

To get the client secret file:

1. In Google Cloud Console, create or use an OAuth Client ID.
2. Choose Desktop app as the application type.
3. Download the JSON file.
4. Save it as `config/secrets/google_oauth_client_secret.json`.

Then run:

```powershell
python scripts\sources\ga4.py
```

The first run will open a browser consent flow. Later runs should reuse or refresh `config/state/ga4_oauth_token.json`.

### Service Account Fallback

Service-account auth is still supported by setting `auth_mode` to `service_account` in `config/sources/monthly/ga4.json`.

Do not store service account JSON keys in this project folder unless you intentionally want them synced/backed up. Prefer keeping keys somewhere private and referencing them with an environment variable.

Service-account environment setup:

```powershell
$env:SCORECARD_GA4_SERVICE_ACCOUNT_FILE = "C:\Path\To\service-account-key.json"
$env:GA4_AM_PROPERTY_ID = "123456789"
$env:GA4_APP_PROPERTY_ID = "987654321"
```

Config template:

- `config/examples/ga4.json`

When ready, copy it to:

- `config/sources/monthly/ga4.json`

Then fill in property IDs directly or use the environment variable names already shown in the template.

Important GA4 access requirement:

- The OAuth user or service account must have at least Viewer access on the relevant GA4 properties.

Current GA4 implementation status:

- `scripts/sources/ga4.py` can load OAuth or service-account credentials.
- It can run configured GA4 reports through the Analytics Data API.
- It returns structured records for the later scorecard writer step.
- `scripts/commands/write_ga4_monthly.py` can write returned GA4 records to the shared Google Sheet for source-specific testing.
- The current config uses `latest_completed_month`, so on July 7, 2026 it targets June 2026 and labels that row `2026-06-01`.
- The app GA4 report currently fails until the OAuth user has access to property `306444817`.

Dry-run GA4 writes:

```powershell
python scripts\commands\write_ga4_monthly.py --dry-run
```

Write GA4 data to the shared Google Sheet:

```powershell
python scripts\commands\write_ga4_monthly.py
```

Dry-run the full monthly pipeline:

```powershell
python scripts\commands\run_monthly_scorecard.py --dry-run
```

Run the full monthly pipeline:

```powershell
python scripts\commands\run_monthly_scorecard.py
```

