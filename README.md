# SME Media Automated Scorecard

This dashboard displays SME Media performance and updates the shared weekly and monthly scorecards. It is intended for routine use in a web browser.

## Important links

- [Open the Automated Scorecard](https://smescorecard.streamlit.app/)
- [Shared Scorecard](https://docs.google.com/spreadsheets/d/1byunytq2svgs56Sp4xwogYEhQOAv2xHw5HTELfzBRi4/edit)
- [SMEMedia repository](https://github.com/SMEMedia/Scorecard)

## View the dashboard

1. Open the app and choose **View dashboard**.
2. Choose **Monthly** or **Weekly**.
3. Use the date and metric controls to explore results.

## Update the scorecard

1. Choose **Update scorecard**, then **Weekly** or **Monthly**.
2. If podcast downloads are needed, download Libsyn **Total Downloads** for **Last 90 Days** as a CSV and upload it. If omitted, podcast downloads are skipped.
3. Leave **Preview only** selected and choose **Preview update**.
4. Open **Update details** and review every planned change.
5. If the preview is correct, clear **Preview only**, select the confirmation box, and choose **Update scorecard now**.
6. Keep the page open until the green success message appears.

Weekly updates use the latest completed Saturday. Monthly updates use the latest completed calendar month. Formula-owned and manually maintained columns are protected from automatic replacement.

## Understand the results

The update collects available information from GA4, Google Search Console, HubSpot, YouTube, Libsyn, app stores, and social platforms. A source may be unavailable while the other sources complete. **Update details** shows the result for each source.

The first successful saved update for a reporting period creates a snapshot. Later updates may reuse that snapshot so historical results do not change unexpectedly.

## Troubleshooting

### An update appears to be stuck

- Keep the page open; the app contacts several services.
- Do not select the update button again.
- If no progress appears after 20 minutes, expand **Update details** and capture the message.
- Send the reporting frequency, date, time, preview/saved status, and screenshot to support.

### A source is marked unavailable

- Review the source-specific message under **Update details**.
- Confirm the reporting period is valid and try one new preview.
- If the same source fails again, contact the owner of that system. Other successful sources do not need to be rerun repeatedly.

### YouTube authorization expired

1. Choose **Reconnect YouTube**.
2. Select **Start YouTube sign-in**, then **Continue to Google**.
3. Sign in with an account that manages the SME Media YouTube channel.
4. Approve the requested read-only access.
5. Follow the on-screen instructions for saving the refreshed authorization in Streamlit.
6. Run a preview update.

If you cannot access Streamlit settings, send the generated authorization block securely to the assigned Streamlit owner. Do not place it in GitHub, email, tickets, or chat.

### Podcast downloads are missing

- Confirm the Libsyn file covers **Last 90 Days** and is a CSV.
- Confirm it was uploaded before running the preview.
- Review **Update details** for the Libsyn result.

### Values do not match another report

- Confirm both reports use the same reporting period.
- Check whether the source system finalized recent information after the scorecard snapshot was created.
- Do not overwrite a historical snapshot without approval from the scorecard owner.
- Record the metric, period, expected value, displayed value, and source report before escalating.

### The shared Sheet was not updated

- Confirm **Preview only** was cleared.
- Confirm the confirmation box was selected.
- Look for the green saved-update message.
- If a permissions message appears, ask the Google Workspace owner to confirm that the dashboard account can edit the shared Scorecard.

## Ongoing maintenance

- Always preview before saving.
- Keep the Streamlit app restricted to approved SME users because it can update the shared Scorecard.
- Keep source-system and Streamlit ownership assigned to current SME staff.
- Escalate credential rotation, snapshot corrections, permissions, and deployment errors to the assigned technical owner.

