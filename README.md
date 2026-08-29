# Wedding Venue Control Center

A private FastAPI dashboard for managing wedding-venue outreach without manually tracking Gmail threads.

## Current workflow

1. Add a venue in the dashboard.
2. Choose **Save draft** or **Save & send inquiry**. Sending only happens after the explicit send action.
3. Use **Check Gmail** to reconcile sent messages and replies.
4. The application stores the complete message privately, asks DigitalOcean Serverless Inference for a short synthesis, and displays only that synthesis in the dashboard.

The application database is the source of truth. The existing Google Sheet can be imported once to seed venues, but it no longer controls the workflow.

## What is implemented

- Venue form with name, location, email, website, and phone
- Explicit draft/save-and-send actions
- Exact-email Gmail matching and idempotent message ingestion
- Sent and responded status tracking
- Focused Kimi response synthesis through DigitalOcean Serverless Inference
- Full email bodies stored in the database but excluded from dashboard/API venue responses
- SQLite for local development and PostgreSQL-compatible production storage
- Optional one-time import from the existing `Venues` Sheet

PDF quote extraction is the next layer. The current milestone tracks and summarizes email replies; it does not yet write structured PDF pricing into the database.

## Local setup

Requirements: Python 3.11 or newer.

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --env-file .env --port 8001
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001). API documentation is at `/docs`.

To test:

```bash
pytest -q
```

## Configuration

Copy `.env.example` to `.env` and enter credentials locally. Never commit `.env`, OAuth client JSON, refresh tokens, model keys, or the local `data/` directory.

Key settings:

```dotenv
# Local default. App Platform should use a managed PostgreSQL connection URL.
DATABASE_URL=sqlite:///data/wedding.db

DIGITALOCEAN_MODEL_ACCESS_KEY=
DIGITALOCEAN_MODEL_ID=
DIGITALOCEAN_INFERENCE_BASE_URL=https://inference.do-ai.run

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
GOOGLE_SPREADSHEET_ID=
GOOGLE_VENUES_SHEET=Venues

# Keep disabled while testing.
AUTO_SEND=false
```

The model access-key name shown in DigitalOcean is not the model ID. Use the exact model identifier supported by the inference endpoint.

`DIGITALOCEAN_API_TOKEN` is separate. It is used by `doctl` or development tooling to manage DigitalOcean resources; the running wedding application does not need it.

## Architecture

```text
Dashboard ──> FastAPI ──> SQLite locally / PostgreSQL in production
                    │
                    ├──> Gmail API: send and reconcile messages
                    │
                    ├──> Serverless Inference: concise reply synthesis
                    │
                    └──> Google Sheets: optional one-time venue import
```

Application code owns sending rules, state, matching, and deduplication. Kimi has one bounded job: convert a reply into a concise summary and status. This does not require a general-purpose autonomous agent.

## Repository map

```text
app/main.py              FastAPI routes and dashboard entry point
app/database.py          Venue, outreach, and message persistence
app/db_workflow.py       Save/send and Gmail reconciliation workflow
app/gmail_oauth.py       Google OAuth connection
app/gmail.py             Gmail API and message normalization
app/inference.py         DigitalOcean reply synthesis
app/sheets.py            Optional Google Sheet import client
app/static/              Private control-center interface
tests/                   Unit and API tests
```

## Production next steps

1. Provision DigitalOcean Managed PostgreSQL and set `DATABASE_URL` as an App Platform secret.
2. Deploy this version of the app and configure Google OAuth secrets for the hosted callback URL.
3. Run Gmail reconciliation on a schedule so replies appear without pressing **Check Gmail**.
4. Add text-only PDF extraction and structured quote fields such as price, capacity, inclusions, and availability.
5. Add ranking and visit scheduling after quote data is reliable.
