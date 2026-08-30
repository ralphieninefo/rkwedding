# Wedding Venue Control Center

A private FastAPI dashboard for managing wedding-venue outreach without manually tracking Gmail threads.

## Live deployment

The current `main` branch is deployed on DigitalOcean App Platform:

- App: [https://rkwedding-az2zo.ondigitalocean.app](https://rkwedding-az2zo.ondigitalocean.app)
- Health check: [`/health`](https://rkwedding-az2zo.ondigitalocean.app/health)
- Access: private HTTP Basic authentication configured in App Platform
- Source: [`ralphieninefo/rkwedding`](https://github.com/ralphieninefo/rkwedding), branch `main`

The web service is live and healthy. The hosted environment still needs the existing DigitalOcean PostgreSQL database attached and the Google OAuth and Serverless Inference variables configured. Until then, Gmail synchronization, Kimi synthesis, and persistent venue data work locally but are not fully enabled on the hosted app. Never put production secret values in this README or the repository.

## Current workflow

1. Add a venue in the dashboard.
   You can paste its public website to discover the name, email, and phone, then review the result.
2. Choose **Save venue** or **Save & send inquiry**. Sending only happens after the explicit send action.
3. Use **Check Gmail** to reconcile sent messages and replies.
4. The application stores the complete message privately, asks DigitalOcean Serverless Inference for a short English synthesis and 90-guest price estimate, and displays only that synthesis in the dashboard.
5. Use **View reply in Gmail** to open the exact tracked conversation, read the full response, and answer there.

The application database stores workflow state and message history. The existing Google Sheet remains the reference source for venue metadata such as region, capacity, vibe, and notes; that metadata is refreshed during Gmail reconciliation.

## What is implemented

- Venue form with name, region, location, email, website, and phone
- Compact tracking dashboard with first outreach, latest English synthesis, workflow step, and direct Gmail link
- Dashboard search and filters for response state, recently added venues, and recent Gmail activity
- Separate searchable venue directory with contact details, metadata, pricing, and conversation history
- Explicit draft/save-and-send actions
- Exact-email Gmail matching and idempotent message ingestion
- Sent and responded status tracking
- Focused English Kimi response synthesis and price estimation through DigitalOcean Serverless Inference
- Persistent last-successful Gmail refresh time
- Human-written replies opened directly in the correct Gmail thread
- Safe public website contact discovery with an explicit send confirmation
- Full email bodies stored in the database but excluded from dashboard/API venue responses
- SQLite for local development and PostgreSQL-compatible production storage
- Initial Sheet import plus ongoing metadata refresh for tracked venues

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
                    └──> Google Sheets: initial import + reference metadata refresh
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

1. Attach the existing DigitalOcean Managed PostgreSQL database named `rkwedding` to the App Platform service and bind its connection URL as `DATABASE_URL`.
2. Configure `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN` as App Platform runtime variables. Store secret values as encrypted secrets.
3. Configure `DIGITALOCEAN_MODEL_ACCESS_KEY` as an encrypted secret and `DIGITALOCEAN_MODEL_ID` as a normal runtime value.
4. Verify the hosted Google OAuth callback, import the existing Sheet metadata, and run one controlled Gmail reconciliation.
5. Schedule Gmail reconciliation so replies appear without pressing **Check Gmail**.
6. Add text-only PDF extraction and structured quote fields such as price, capacity, inclusions, and availability.
7. Add ranking and visit scheduling after quote data is reliable.
