# SME Media Scorecard

This app displays the SME Media performance dashboard and updates the shared weekly and monthly scorecards. Day-to-day users do not need Python, GitHub, or any other software installed.

## For scorecard users

Open the hosted Streamlit app in your web browser.

### View the dashboard

1. Choose **View dashboard** in the left menu.
2. Choose **Monthly** or **Weekly**.
3. Use the date and metric controls to explore results.

### Update a scorecard

1. Choose **Update scorecard** in the left menu.
2. Choose **Weekly** or **Monthly**.
3. Optional: In Libsyn, download **Total Downloads** for **Last 90 Days** as CSV and drag it into the upload box. If omitted, podcast downloads are skipped.
4. Leave **Preview only** checked and select **Preview update**.
5. Open **Update details** and review the planned changes.
6. If the preview looks correct, clear **Preview only**.
7. Check the confirmation box and select **Update scorecard now**.
8. Wait for the green success message before closing the page.

The weekly update uses the latest completed Saturday. The monthly update uses the latest completed calendar month. Updates may take several minutes because the app contacts each source system.

### If something goes wrong

Do not repeatedly press the update button. Expand **Update details**, copy the message, and send it to the scorecard administrator with:

- whether you chose Weekly or Monthly;
- whether it was a preview or real update;
- the date and approximate time;
- a screenshot of the message.

The shared scorecard is here: [Google Scorecard](https://docs.google.com/spreadsheets/d/1byunytq2svgs56Sp4xwogYEhQOAv2xHw5HTELfzBRi4/edit).

## What the update does

The app reads available data from GA4, Google Search Console, HubSpot, YouTube, Libsyn, the app stores, and social platforms. It maps those values to the correct row and column in the shared Google Sheet. Formula-owned and manually maintained columns are not overwritten.

The first successful saved run for a reporting period also creates a snapshot. Later runs reuse that snapshot so historical periods do not unexpectedly change.

Some source integrations may report that they are unavailable while the remaining sources complete. The update details identify each source and its status.

## For the scorecard administrator

The rest of this README is for the person who owns the GitHub repository, Streamlit deployment, and source credentials.

### Deploy on Streamlit Community Cloud

1. Connect the GitHub repository to Streamlit Community Cloud.
2. Set the app file to `scripts/dashboards/media_performance_dashboard.py`.
3. Add the credentials described below in the app's **Secrets** settings.
4. Deploy the app and run a Weekly and Monthly preview.
5. Restrict app access to the intended SME users before enabling routine updates.

Never commit credentials to GitHub. Files under `config/secrets/` and `config/state/` are intentionally ignored.

### Streamlit secrets

The Google service account is required for both the dashboard and Google Sheet writes:

```toml
spreadsheet_id = "1byunytq2svgs56Sp4xwogYEhQOAv2xHw5HTELfzBRi4"

[google_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = """-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
"""
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```

Add only the source credentials used by the organization:

```toml
hubspot_private_app_token = "..."
x_bearer_token = "..."
youtube_redirect_uri = "https://YOUR-STREAMLIT-APP.streamlit.app/"
app_store_private_key = """-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
"""

[google_oauth_client_secret]
# Copy the complete contents of the Google OAuth client JSON here.

[youtube_oauth_token]
# Copy the complete authorized-user token JSON here.

[youtube_web_oauth_client]
client_id = "...apps.googleusercontent.com"
project_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_secret = "..."
redirect_uris = ["https://YOUR-STREAMLIT-APP.streamlit.app/"]

[meta]
page_access_token = "..."

[instagram]
access_token = "..."
```

The app converts these settings into temporary, ignored files expected by the existing source integrations. OAuth tokens must already be authorized; a hosted browser cannot complete a local OAuth consent flow.

Libsyn credentials are not stored in Streamlit. The operator manually downloads and uploads the report for each run.

### Refresh the YouTube key

When an update says that YouTube authorization expired or was revoked:

1. Choose **Reconnect YouTube** in the app's left menu.
2. Select **Start YouTube sign-in**, then **Continue to Google**.
3. Sign in with the channel owner/manager account and approve access.
4. After Google returns to Streamlit, copy the generated `[youtube_oauth_token]` block.
5. In Streamlit app settings, open **Secrets**, replace the old token section, save, and wait for the app to restart.
6. Run a preview update.

The app deletes only its temporary runtime copy of the old token. Streamlit does not allow an application to rewrite its own saved Secrets, so the final copy-and-save step is required.

### Source access checklist

- The Google service account can edit the Scorecard Google Sheet.
- The same account can read GA4 property `432233519` and the Search Console property.
- The HubSpot private app has the scopes required by its configured email endpoints.
- The YouTube OAuth token includes YouTube Data read-only and YouTube Analytics read-only scopes.
- App Store Connect and Google Play credentials can read the configured reports.
- Meta, Instagram, and X credentials are current.

Run both previews after changing any credential.

### Local administrator use

Technical administrators can still run the app or automation locally:

```powershell
python -m pip install -r requirements.txt
streamlit run scripts/dashboards/media_performance_dashboard.py

python scorecard.py weekly --dry-run
python scorecard.py weekly
python scorecard.py monthly --dry-run
python scorecard.py monthly
```

Local credentials belong in `config/secrets/`. Runtime tokens and snapshots belong in `config/state/`.

### Project layout

```text
scorecard.py                 Command-line entry point for administrators
config/scorecard.json        Shared Google Sheet settings
config/sources/              Source mappings and reporting rules
scripts/commands/            Weekly and monthly update commands
scripts/dashboards/          Streamlit dashboard and update interface
scripts/lib/                 Google Sheets and runtime-secret helpers
scripts/pipelines/           Rules that protect formula/manual columns
scripts/sources/             Source-system integrations and required helpers
```

### Security and maintenance

- Rotate a credential immediately if it appears in Git, email, chat, or screenshots.
- Review source account ownership before an employee leaves.
- Keep the Streamlit app private because it can write to the shared scorecard.
- Use preview before every routine saved update.
- Keep snapshots in mind when correcting a previously captured reporting period; snapshot refresh is an administrator-only operation.
