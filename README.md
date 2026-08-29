# Wedding Venue Agent

A Python service for event-driven wedding venue outreach, reply analysis, quote tracking, negotiation support, and viewing coordination.

## Phase 1

Phase 1 is a local FastAPI service with a browser dashboard at `http://127.0.0.1:8000`. The dashboard sends normalized Gmail events to `POST /events/gmail` and displays a validated structured decision. When a model access key and model ID are configured, the backend calls DigitalOcean Serverless Inference at `https://inference.do-ai.run/v1/chat/completions`. Without those settings it returns a safe placeholder response.

The service also accepts and decodes Google Cloud Pub/Sub envelopes at `POST /events/gmail/push`. Gmail's push payload contains only the mailbox address and a history ID, so Gmail OAuth, `history.list`, complete-thread retrieval, and Sheet updates remain the next integration slice. See `docs/GMAIL_SETUP.md`.

## Local setup

Requirements: Python 3.11 or newer.

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --env-file .env
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser.

Check the service directly:

```bash
curl http://127.0.0.1:8000/health
```

Send a fake Gmail event:

```bash
curl -X POST http://127.0.0.1:8000/events/gmail \
  -H 'Content-Type: application/json' \
  -d '{"venue":"Villa Test","message":"Il prezzo è €28.000 per 90 persone."}'
```

Without inference credentials, the expected safe response is:

```json
{
  "venue": "Villa Test",
  "event_type": "unprocessed",
  "status": "received",
  "recommended_action": "connect_serverless_inference",
  "quoted_price": null,
  "currency": null
}
```

## Configuration

`.env` is ignored by Git and contains only blank placeholders. Never commit model access keys, Google credentials, OAuth tokens, or other secrets.

```dotenv
DIGITALOCEAN_MODEL_ACCESS_KEY=
DIGITALOCEAN_MODEL_ID=
AUTO_SEND=false
```

Keep `AUTO_SEND=false` while reply classification and drafting are being tested.

The two DigitalOcean credentials have different responsibilities:

- `DIGITALOCEAN_API_TOKEN` is used by Codex MCP or `doctl` to manage infrastructure. It is not an application setting.
- `DIGITALOCEAN_MODEL_ACCESS_KEY` is used only by the FastAPI backend to call Serverless Inference.

## Current event flow

```text
Gmail users.watch
      ↓
Google Cloud Pub/Sub push
      ↓
POST /events/gmail/push
      ↓
decode emailAddress + historyId
      ↓
NEXT: Gmail history.list + full thread fetch
      ↓
POST /events/gmail normalized event
      ↓
DigitalOcean Serverless Inference
      ↓
validated AgentDecision
```

The Pub/Sub endpoint can use a shared URL token during local development:

```text
https://your-app.example/events/gmail/push?token=<GOOGLE_PUBSUB_VERIFICATION_TOKEN>
```

Use authenticated Pub/Sub push with OIDC before production. Never put Google or DigitalOcean credentials in browser code.

## Repository map

```text
app/main.py                 FastAPI application and routes
app/agent.py                Agent decision boundary
app/config.py               Environment-backed settings
app/inference.py            DigitalOcean Serverless Inference client
app/gmail.py                Gmail integration boundary
app/sheets.py               Google Sheets integration boundary
app/models.py               Typed request and response models
app/static/index.html       Local dashboard structure
app/static/styles.css       Dashboard visual design
app/static/app.js           Dashboard interactions
prompts/wedding-agent.md     Workflow policy and approval rules
docs/ARCHITECTURE.md         System boundaries and delivery phases
docs/GMAIL_SETUP.md          Google Cloud and Gmail push setup checklist
CODEX_HANDOFF.md             Reusable prompt for a new Codex task
tests/                       API, Pub/Sub, and inference boundary tests
```
