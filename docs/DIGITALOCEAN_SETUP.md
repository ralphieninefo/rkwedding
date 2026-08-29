# DigitalOcean Setup

The repository can run locally without `doctl`. DigitalOcean terminal or MCP access is needed only when you are ready to inspect models, create the App Platform app, configure secrets, or view deployment logs.

## Credentials have separate jobs

| Credential | Used by | Purpose |
|---|---|---|
| `DIGITALOCEAN_API_TOKEN` | `doctl` or DigitalOcean MCP | Infrastructure management |
| `DIGITALOCEAN_MODEL_ACCESS_KEY` | FastAPI app | Serverless Inference requests |

Do not substitute one for the other and do not commit either value.

## App Platform shape

Connect App Platform to `ralphieninefo/rkwedding`, branch `main`. The included `Procfile` starts FastAPI on App Platform's assigned port.

Configure these encrypted runtime secrets in App Platform:

- `DIGITALOCEAN_MODEL_ACCESS_KEY`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_PUBSUB_VERIFICATION_TOKEN`
- `GOOGLE_SHEET_WEBHOOK_TOKEN`

Configure the model ID, Google client ID, spreadsheet ID, and tab names as ordinary runtime environment values. Keep `AUTO_SEND=false` during verification.

After deployment, verify `/health`, the dashboard, one redacted inference example, one test Sheet row, and one Pub/Sub test message before connecting real venue email.
