# Wedding Venue Agent

An event-driven Python service for venue outreach, Gmail reply processing, PDF quote extraction, Google Sheet tracking, and transparent venue comparison.

The model has one bounded job: classify messages and extract explicit quote facts. Application code owns email, state, deduplication, scoring, and approvals. This is intentionally not a continuously running general agent.

## Current milestone: response tracking

- Focused local dashboard at `http://127.0.0.1:8001`
- Read-only Google OAuth connection from the dashboard
- Manual scan of recent Gmail threads for replies to sent messages
- Local SQLite response list; no inbox changes and no automatic sending

See [read-only Gmail setup](docs/GMAIL_READONLY_SETUP.md). The earlier inference,
quote-analysis, and workflow prototype remains available at `/analysis`, but it
is not part of this milestone.

## Earlier prototype capabilities

- DigitalOcean Serverless Inference boundary with validated JSON output
- Deterministic venue ranking at `POST /compare` and in the dashboard
- New Sheet row webhook with Gmail duplicate checking
- Draft-only initial outreach by default
- Gmail Pub/Sub decoding, `history.list` pagination, and durable Sheet checkpoints
- Full Gmail thread loading and local text extraction from PDF attachments
- Quote and venue-row updates in Google Sheets
- Fixed, non-binding acknowledgement drafts for received quotes
- Server-side Google OAuth refresh support

Nothing sends automatically unless `AUTO_SEND=true`. Quote acknowledgements remain drafts even in the current auto-send mode.

## Local setup

Requirements: Python 3.11 or newer.

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --env-file .env --port 8001
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001). API documentation is available at `/docs`.

Run the test suite:

```bash
pytest -q
```

## Configuration

Never commit `.env`, OAuth credentials, refresh tokens, or model keys.

```dotenv
DIGITALOCEAN_MODEL_ACCESS_KEY=
DIGITALOCEAN_MODEL_ID=

GOOGLE_PUBSUB_VERIFICATION_TOKEN=
GOOGLE_SHEET_WEBHOOK_TOKEN=
GOOGLE_SPREADSHEET_ID=

# Local, short-lived option:
GOOGLE_ACCESS_TOKEN=

# Durable server-side option for App Platform:
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=

AUTO_SEND=false
```

`DIGITALOCEAN_API_TOKEN` is separate: Codex MCP or `doctl` uses it to manage DigitalOcean resources. The running application does not use it. See [DigitalOcean deployment](docs/DIGITALOCEAN_SETUP.md).

## Tracker tabs

Copy `google-apps-script/Code.gs` into the Sheet's Apps Script project and run `setupTrackerTabs()` once. It adds missing tabs without overwriting populated tabs:

- `Venues`: contact and current workflow state
- `Quotes`: append-only normalized quote records
- `System`: Gmail history checkpoints and processed-message IDs

Set a venue row's `Status` to `Ready` to trigger outreach. With the safe default, the backend checks Gmail for an existing conversation, creates one draft, and changes the status to `Draft created`. See [Google and Gmail setup](docs/GMAIL_SETUP.md).

## Event flow

```text
Sheet row set to Ready ──> Apps Script ──> FastAPI ──> duplicate check ──> Gmail draft

Gmail users.watch ──> Pub/Sub ──> FastAPI ──> history.list ──> full thread + PDF
                                                    │
                                                    v
                                      Serverless Inference extraction
                                                    │
                                                    v
                                     Sheet update + acknowledgement draft

Sheet quote facts ──> deterministic scoring ──> ranked shortlist ──> human selects visits
```

## Repository map

```text
app/main.py                     FastAPI routes and local dashboard
app/gmail_oauth.py              Local read-only Gmail connection
app/gmail_sync.py               Recent reply detection
app/response_tracker.py         Local SQLite response store
app/workflow.py                 Event orchestration and approval boundaries
app/gmail.py                    Gmail REST and MIME normalization
app/sheets.py                   Header-aware Sheets REST client
app/documents.py                Private local PDF text extraction
app/inference.py                DigitalOcean Serverless Inference client
app/scoring.py                  Fixed, auditable ranking formula
app/models.py                   Validated request, quote, and ranking models
google-apps-script/Code.gs      Sheet trigger and tab setup
prompts/wedding-agent.md        Extraction and workflow policy
docs/                           Architecture and setup guides
tests/                          Unit and API tests
```

## Known next steps

- Complete one real Google OAuth consent run and store the refresh token as an App Platform secret.
- Create the Gmail Pub/Sub topic/subscription and start `users.watch`.
- Configure a DigitalOcean model access key and verify extraction against real, redacted quotes.
- Add OCR/vision fallback for scanned PDFs; they are currently flagged for manual review.
- Add expired-history reconciliation for Gmail checkpoints that fall outside Gmail's available history window.
- Add Drive upload links if PDFs should be archived outside Gmail.
- Add Calendar integration only after the ranking and visit-approval flow is verified.
