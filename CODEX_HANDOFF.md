# Codex Handoff: Wedding Venue Agent

## Prompt to paste into a new Codex task

Continue building the existing Python repository in this folder as a production-minded wedding venue agent for Kassia and Raphaël.

Work in this order and do not skip ahead:

1. **Git and repository baseline**
   - Inspect the current Git state and preserve existing work.
   - Confirm `.env` and `.venv/` are ignored and no credentials are tracked.
   - Review the existing FastAPI scaffold, prompt policy, tests, and local dashboard.
   - The GitHub remote is `ralphieninefo/rkwedding`; preserve its history and never force-push.

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
   - Maintain the existing server-side call to `https://inference.do-ai.run`.
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

- GitHub repository is connected on `main`.
- FastAPI and the local dashboard are working, including deterministic venue comparison.
- DigitalOcean Serverless Inference, structured quote extraction, and validation are implemented.
- Gmail REST, Pub/Sub history processing, full-thread retrieval, draft creation, and PDF extraction are implemented.
- Google Sheets REST updates, durable checkpoints, and the Apps Script `Ready` trigger are implemented.
- Google OAuth refresh is implemented but real credentials have not been configured or tested.
- `AUTO_SEND=false`; no real secrets are stored in the repository.
- Next: configure test OAuth credentials, create Gmail Pub/Sub infrastructure, verify one controlled end-to-end flow, then deploy to App Platform with encrypted secrets.
