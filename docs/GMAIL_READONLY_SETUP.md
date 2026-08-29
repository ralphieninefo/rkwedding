# Connect Gmail to the local response tracker

This first milestone asks Google for **read-only Gmail access**. It cannot send,
delete, archive, label, or otherwise change email.

## One-time Google setup

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and select
   or create the project for this app.
2. Open **APIs & Services → Library**, find **Gmail API**, and enable it.
3. Open **Google Auth Platform**. Configure the consent screen and add the Gmail
   account you will connect as a test user if the app is in testing mode.
4. Open **Clients → Create client → Web application**.
5. Add this exact authorized redirect URI:

   ```text
   http://127.0.0.1:8001/auth/google/callback
   ```

6. Download the client JSON. Save it inside this repository as:

   ```text
   data/google_client_secret.json
   ```

Do not paste that file into chat and do not commit it. The entire `data/` folder
is ignored by Git.

## Connect and scan

Start the local app on port 8001, open <http://127.0.0.1:8001/>, and select
**Connect Gmail**. After accepting Google's read-only permission, select
**Check for replies**.

The tracker scans up to 100 inbox threads from the last 30 days. It records a
thread only when Gmail shows that you sent a message and a recipient replied
afterward. Results are stored locally in `data/responses.db`.
