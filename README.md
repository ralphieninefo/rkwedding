<div align="center">

# Wedding Venue Control Center

**Private venue outreach, response tracking, and quote comparison for Kassia & Raphaël.**

[Live app](https://rkwedding-az2zo.ondigitalocean.app) · [Health check](https://rkwedding-az2zo.ondigitalocean.app/health) · [Architecture](docs/ARCHITECTURE.md)

![Python](https://img.shields.io/badge/Python-3.12-173d2e?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-private_API-245843?style=flat-square)
![DigitalOcean](https://img.shields.io/badge/DigitalOcean-App_Platform-0069ff?style=flat-square)
![Tests](https://img.shields.io/badge/tests-43_passing-dfe9df?style=flat-square&labelColor=245843)

</div>

---

## What it does

The control center turns venue outreach into one tracked workflow:

```text
Add venue → Send inquiry → Track Gmail thread → Synthesize reply → Compare options
```

- Paste a venue website to discover its public contact details.
- Save the venue or explicitly send the Italian inquiry email.
- Match sent messages and replies to the correct Gmail thread.
- Use DigitalOcean Serverless Inference to produce a concise English synthesis.
- Track first outreach, latest activity, response state, and 90-guest pricing.
- Open the exact Gmail conversation to read or answer the full reply.
- Keep venue metadata aligned with the existing Google Sheet.

## Product surfaces

| Surface | Purpose |
|---|---|
| **Tracking** | Search and filter outreach by response state, date added, recent Gmail activity, or venue name. |
| **All venues** | Reference directory for contacts, location, capacity, vibe, pricing, notes, and conversation history. |
| **Gmail** | Source for complete messages and human-written replies. The app displays only concise syntheses. |
| **Google Sheet** | Reference source for venue research and metadata. |

## Current status

| Capability | Local | Hosted |
|---|:---:|:---:|
| Dashboard and venue directory | ✅ | ✅ |
| Password-protected access | — | ✅ |
| Gmail read/send | ✅ | Needs production OAuth |
| Google Sheet metadata refresh | ✅ | Needs production OAuth |
| Kimi reply synthesis | ✅ | Needs model credentials |
| Persistent storage | SQLite | Managed PostgreSQL configured in the app spec |
| Text PDF extraction | Planned | Planned |

The App Platform service is live and healthy at [rkwedding-az2zo.ondigitalocean.app](https://rkwedding-az2zo.ondigitalocean.app). Production secrets are intentionally not stored in Git.

## Architecture

```text
                         ┌─────────────────────────┐
                         │   Control Center UI     │
                         │ Tracking · Directory   │
                         └────────────┬────────────┘
                                      │
                                      ▼
┌──────────────┐          ┌─────────────────────────┐          ┌─────────────────────┐
│ Google Sheet │◀────────▶│       FastAPI app       │◀────────▶│ PostgreSQL / SQLite │
│ Venue data   │          │ Rules · matching · API │          │ Workflow state      │
└──────────────┘          └────────────┬────────────┘          └─────────────────────┘
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                ┌─────────────────┐      ┌────────────────────┐
                │    Gmail API    │      │ DO Serverless      │
                │ Threads/replies │      │ Inference · Kimi   │
                └─────────────────┘      └────────────────────┘
```

Application code owns sending rules, state, matching, and deduplication. The model has one bounded job: turn a venue response into a structured English summary and price estimate. A general-purpose autonomous agent is not required.

## Run locally

Requires Python 3.12.

```bash
git clone https://github.com/ralphieninefo/rkwedding.git
cd rkwedding

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
uvicorn app.main:app --reload --env-file .env --port 8001
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001).

```bash
pytest -q
```

## Configuration

Keep local credentials in `.env`. Never commit `.env`, OAuth client JSON, refresh tokens, model keys, or the `data/` directory.

| Variable | Type | Purpose |
|---|---|---|
| `APP_ENV` | General | Defaults to `local`; the hosted app must set `production`. |
| `ALLOW_UNAUTHENTICATED_LOCAL` | General | Allows password-free local use only. Never enable it on the hosted app. |
| `DATABASE_URL` | Secret | SQLite locally; a PostgreSQL connection URL is mandatory outside local mode. |
| `DIGITALOCEAN_MODEL_ACCESS_KEY` | Secret | Calls DigitalOcean Serverless Inference. |
| `DIGITALOCEAN_MODEL_ID` | General | Exact model identifier, not the access-key name. |
| `GOOGLE_CLIENT_ID` | General | Google OAuth application identifier. |
| `GOOGLE_CLIENT_SECRET` | Secret | Google OAuth application secret. |
| `GOOGLE_CLIENT_SECRET_JSON` | Secret | Complete Google OAuth client JSON for hosted deployments; preferred over the local client file. |
| `GOOGLE_REFRESH_TOKEN` | Secret | Server-side Gmail and Sheets access. |
| `GOOGLE_SPREADSHEET_ID` | General | Wedding venue master spreadsheet. |
| `GOOGLE_VENUES_SHEET` | General | Venue tab name; defaults to `Venues`. |
| `GOOGLE_ALLOWED_EMAILS` | General | Comma-separated Gmail accounts permitted to connect to this private app. |
| `CONTROL_CENTER_PASSWORD` | Secret | Protects the hosted dashboard. |
| `CONTROL_CENTER_SESSION_TTL_HOURS` | General | Signed login lifetime; defaults to seven days. |

`DIGITALOCEAN_API_TOKEN` is only for `doctl` or infrastructure tooling. The running application does not use it for inference.

Google's refreshable OAuth credentials are stored in PostgreSQL, so Gmail stays
connected across container restarts. Existing accounts may reconnect; a new
account is accepted only when its address appears in `GOOGLE_ALLOWED_EMAILS`.
If an older `data/google_token.json` is present while the database is empty, it
is imported once; the database is authoritative after that.

The application refuses to start with SQLite whenever `APP_ENV` is not `local`.
Production therefore requires the managed PostgreSQL binding configured in
`.do/app.yaml`. It also refuses to start without `CONTROL_CENTER_PASSWORD`
unless the local-only bypass is explicitly enabled.

## Repository map

```text
app/
├── main.py          FastAPI routes and UI entry points
├── database.py      Venue, outreach, message, and pricing models
├── db_workflow.py   Gmail reconciliation and Sheet metadata sync
├── gmail.py         Gmail API and message normalization
├── gmail_oauth.py   Google OAuth flow and database-backed token lifecycle
├── inference.py     Structured reply synthesis
├── sheets.py        Google Sheet integration
└── static/          Tracking dashboard and venue directory

tests/               API, workflow, integration, and scoring tests
.do/app.yaml         DigitalOcean App Platform specification
```

## Production checklist

- [x] Deploy the FastAPI service from GitHub `main`.
- [x] Protect the hosted control center with a signed, HttpOnly login session.
- [x] Restrict new Gmail connections with a server-side email allowlist.
- [x] Define managed PostgreSQL and its `DATABASE_URL` binding in the app spec.
- [ ] Fill the encrypted `CONTROL_CENTER_PASSWORD` placeholder in App Platform.
- [ ] Add encrypted Google OAuth runtime secrets.
- [ ] Add the encrypted model access key and model ID.
- [ ] Verify one hosted Gmail reconciliation with a controlled venue thread.
- [x] Schedule reconciliation so replies appear automatically.
- [ ] Add text-only PDF extraction for quote attachments.
- [ ] Add venue ranking and visit scheduling after quote data is reliable.

## Safety rules

- Sending requires an explicit user action.
- Full email bodies stay in the database and are excluded from venue API responses.
- The dashboard opens Gmail for human-written replies instead of autonomously negotiating.
- Credentials remain outside Git and must be encrypted in App Platform.
- A dashboard login does not authorize an arbitrary Gmail account; Google OAuth
  callbacks are checked against the backend allowlist before tokens are stored.
- Reconciliation is idempotent: the same Gmail message is not processed twice.
