# Wedding Venue Agent Architecture

## System boundary

The application is an event-driven wedding venue workflow, not a continuously running agent session.

```text
Gmail push event
      |
      v
FastAPI service on DigitalOcean App Platform
      |
      +--> Load the complete Gmail thread
      +--> Load the matching Google Sheet row
      |
      v
DigitalOcean Serverless Inference
      |
      v
Validated structured decision
      |
      +--> Update Google Sheet state
      +--> Create a Gmail draft
      +--> Request human approval when required
```

The dashboard is a control and review surface. It never receives cloud credentials and does not call DigitalOcean directly.

## Component responsibilities

### FastAPI application

- Receives normalized Gmail events.
- Loads durable state from Gmail and Google Sheets.
- Calls Serverless Inference with the wedding policy and current context.
- Validates the model response.
- Applies approval rules before calling external tools.
- Serves the local dashboard and, later, the deployed dashboard.

### DigitalOcean Serverless Inference

- Performs message classification, fact extraction, quote analysis, and recommended-action reasoning.
- Returns structured data; it does not own workflow state.
- Uses `DIGITALOCEAN_MODEL_ACCESS_KEY` on the server only.

### Gmail

- Provides event ingress and complete conversation history.
- Stores venue correspondence as durable business context.
- Receives drafts by default; automatic sending remains disabled until explicitly approved.

### Google Sheets

- Acts as the initial venue CRM and workflow-state store.
- Tracks contact state, quotes, inclusions, missing information, follow-up dates, and viewing status.

### DigitalOcean MCP

- Gives Codex controlled access to DigitalOcean documentation, the model catalog, App Platform configuration, deployments, and logs.
- Uses `DIGITALOCEAN_API_TOKEN`.
- Is a development and operations tool; the wedding application does not depend on MCP at runtime.

## Credentials

| Credential | Consumer | Purpose | Repository policy |
|---|---|---|---|
| `DIGITALOCEAN_API_TOKEN` | Codex MCP or `doctl` | Manage DigitalOcean resources | Never store or commit |
| `DIGITALOCEAN_MODEL_ACCESS_KEY` | FastAPI backend | Call Serverless Inference | `.env` locally; encrypted runtime secret in App Platform |
| Google OAuth credentials | FastAPI backend | Gmail and Sheets access | Never expose to browser or commit |

## Approval boundaries

Human approval is required before:

- sending negotiation replies;
- confirming or changing a viewing;
- creating a binding calendar event;
- accepting pricing or contractual terms;
- paying a deposit;
- creating, updating, or deleting paid cloud resources.

Read-only discovery, local tests, draft generation, and non-binding Sheet updates can be automated once their integrations are verified.

## Delivery phases

1. Establish and inspect the Git baseline.
2. Confirm architecture and policy boundaries.
3. Connect Codex to DigitalOcean MCP with least-privilege credentials.
4. Implement and test Serverless Inference locally.
5. Connect Gmail and Google Sheets using test data and draft-only behavior.
6. Finish the dashboard against verified backend capabilities.
7. Prepare and approve an App Platform deployment.
