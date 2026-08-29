# Codex Handoff: Wedding Venue Agent

## Prompt to paste into a new Codex task

Continue building the existing Python repository in this folder as a production-minded wedding venue agent for Kassia and Raphaël.

Work in this order and do not skip ahead:

1. **Git and repository baseline**
   - Inspect the current Git state and preserve existing work.
   - Confirm `.env` and `.venv/` are ignored and no credentials are tracked.
   - Review the existing FastAPI scaffold, prompt policy, tests, and local dashboard.
   - Do not publish, create a GitHub remote, push, or commit unless I explicitly authorize it.

2. **Architecture**
   - Read `docs/ARCHITECTURE.md` and `prompts/wedding-agent.md`.
   - Keep the application event-driven: Gmail event → FastAPI handler → load Gmail thread and Sheet row → DigitalOcean Serverless Inference → structured decision → draft/update tools.
   - Keep persistent state in Gmail and Google Sheets; do not keep an always-running model session.
   - Treat DigitalOcean MCP as a development and infrastructure control plane for Codex, not as an application runtime dependency.
   - Preserve human approval before sending negotiation replies, confirming viewings, creating binding calendar events, signing contracts, or paying deposits.

3. **DigitalOcean MCP and credentials**
   - Verify Codex MCP configuration before making changes.
   - Prefer DigitalOcean's hosted remote MCP endpoints.
   - Enable only the services needed initially: App Platform, Model Catalog, and DigitalOcean Docs.
   - Reference `DIGITALOCEAN_API_TOKEN` from the environment. Never write the token into the repository, a prompt, source code, or logs.
   - Distinguish the credentials:
     - `DIGITALOCEAN_API_TOKEN` lets Codex/MCP manage DigitalOcean infrastructure.
     - `DIGITALOCEAN_MODEL_ACCESS_KEY` lets the application call Serverless Inference.
   - Require approval for infrastructure write operations.
   - Verify read-only access before attempting deployment or mutation.

4. **Backend and Serverless Inference**
   - Replace the placeholder in `app/agent.py` with a server-side call to `https://inference.do-ai.run`.
   - Load `prompts/wedding-agent.md` as the policy.
   - Produce validated structured output matching the Pydantic decision model.
   - Add timeouts, useful error handling, and tests with mocked HTTP responses.
   - Never send the model access key to browser JavaScript.
   - Keep `AUTO_SEND=false` by default.

5. **Frontend**
   - Treat the current local dashboard as a prototype.
   - Connect its status indicators to real backend configuration and inference results.
   - Show clear loading, success, validation, and failure states.
   - Never imply that Gmail, Sheets, inference, or sending is connected until verified.
   - Keep the interface accessible, responsive, and usable locally at `http://127.0.0.1:8000`.

6. **Deployment only after local verification**
   - Run automated tests and a local end-to-end smoke test.
   - Prepare an App Platform app spec only after the inference flow works locally.
   - Store `DIGITALOCEAN_MODEL_ACCESS_KEY` as an encrypted runtime secret in App Platform.
   - Ask for approval before creating or updating cloud resources.

At each stage, report what is already complete, what changed, what was verified, and the next missing dependency. Make reasonable implementation decisions, but stop before any external deployment, Git push, credential creation, email send, calendar commitment, or paid resource creation unless I explicitly approve it.

## Current repository state

- Local Git repository initialized on `main`; no commit or remote has been created.
- Python 3.12 virtual environment exists at `.venv`.
- FastAPI API and local dashboard are working.
- The dashboard is served at `/`; normalized messages are accepted at `POST /events/gmail`.
- The normalized event endpoint calls DigitalOcean Serverless Inference when a model key and model ID are configured, with a safe placeholder otherwise.
- The Gmail Pub/Sub endpoint decodes mailbox and history notifications; OAuth/history retrieval is not implemented yet.
- Google Sheets is not connected yet.
- `AUTO_SEND=false` and no real secrets are stored in the repository.
