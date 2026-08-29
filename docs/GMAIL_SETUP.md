# Google Sheets, Gmail, and Pub/Sub Setup

The code is ready for Google credentials, but no real account or secret is stored in Git.

## 1. Prepare Google Cloud

1. Create or select a Google Cloud project.
2. Enable Gmail API, Google Sheets API, and Cloud Pub/Sub API.
3. Configure the OAuth consent screen and add the wedding mailbox as a test user if the app is still in testing.
4. Create an OAuth client for the server-side application.
5. Complete one consent flow requesting these minimum scopes:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/spreadsheets`
6. Save the client ID, client secret, and refresh token as private environment values. Never place the client secret or refresh token in Apps Script source or browser JavaScript.

For quick local testing, `GOOGLE_ACCESS_TOKEN` can hold a short-lived token. App Platform should use the refresh-token settings so the backend obtains fresh access tokens server-side.

## 2. Prepare the Sheet

1. Open Extensions → Apps Script in the venue tracker.
2. Copy in `google-apps-script/Code.gs` and its manifest.
3. Run `setupTrackerTabs()` once and approve the requested permissions.
4. In Apps Script Project Settings, add Script Properties:
   - `WEBHOOK_URL`: the deployed HTTPS URL, without a trailing slash
   - `WEBHOOK_TOKEN`: the same random value as `GOOGLE_SHEET_WEBHOOK_TOKEN`
5. Run `installVenueReadyTrigger()` once.

The installable trigger runs as the person who installed it. It only calls the backend when a manually edited `Venues` row changes to `Ready`. Script/API updates do not recursively fire the trigger.

## 3. Configure Gmail push

1. Create a Pub/Sub topic in the same project used for Gmail `users.watch`.
2. Grant `gmail-api-push@system.gserviceaccount.com` permission to publish to the topic.
3. Create a push subscription pointing to:

   ```text
   https://<app-host>/events/gmail/push?token=<GOOGLE_PUBSUB_VERIFICATION_TOKEN>
   ```

4. Call Gmail `users.watch` for the wedding mailbox with the fully qualified topic name:

   ```text
   projects/<project-id>/topics/<topic-name>
   ```

5. Store the returned initial history ID in the `System` tab, or allow the first webhook to establish a baseline.
6. Renew the watch daily; Gmail watches expire and must be renewed before their returned expiration.

Gmail notifications contain only `emailAddress` and `historyId`. The backend uses the previous Sheet checkpoint to call `history.list`, fetches each complete thread, processes each Gmail message ID once, and advances the checkpoint only after successful updates.

## 4. Safety checks before real use

- Leave `AUTO_SEND=false`.
- Put a test venue and an address you control in the Sheet.
- Set its status to `Ready` and confirm exactly one Gmail draft appears.
- Send a reply with a small test PDF and verify a `Quotes` row appears.
- Confirm the PDF text and extracted price are accurate before testing real venue material.
- Rotate the webhook tokens if they appear in logs or screenshots.

Use authenticated Pub/Sub push with OIDC before production. The shared URL token is a development boundary, not the final security model.
