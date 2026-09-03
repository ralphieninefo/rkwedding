# Repository guidance for coding agents

Read `docs/PRODUCT_BRIEF.md` before proposing or implementing product changes.
It is the source of truth for the intended user workflow and scope.

## Architectural guardrails

- This is a private tool for Kassia and Raphaël to find their wedding venue,
  not a multi-tenant SaaS product or an autonomous outreach agent.
- Managed PostgreSQL is the application source of truth. Gmail owns the
  original conversations, and one private Spaces bucket mirrors attachments.
- Google Sheets is outside the canonical product. Do not add Sheet imports,
  refreshes, triggers, scopes, or workflow state to the active path.
- App Platform services and jobs are stateless. Never store required state,
  OAuth tokens, or documents in the container filesystem.
- New inquiries use `GOOGLE_PRIMARY_EMAIL`. Replies must use the Google account
  and Gmail thread that received the corresponding inbound message.
- Every outbound message requires an exact preview and an explicit human send
  action. Scheduled jobs may ingest and enrich data but must never send email.
- The dashboard must load entirely from PostgreSQL. It must not require a Gmail
  refresh to render saved state.
- Ingestion and attachment mirroring must remain idempotent.
- Keep full email bodies, OAuth tokens, object keys, and secrets out of browser
  payloads and logs.

## Active implementation

The canonical production path is:

- `app/main.py`: authenticated HTTP/UI boundary
- `app/database.py`: durable models and UI projections
- `app/db_workflow.py`: database-backed outreach, reconciliation, and replies
- `app/venue_state.py`: pure stage/next-action derivation, no DB access
- `app/email_templates.py`: exact human-reviewed outbound copy
- `app/gmail_oauth.py`, `app/gmail.py`: multi-account OAuth and Gmail API
- `app/scheduled_sync.py`: 15-minute production reconciliation entry point
- `app/storage.py`: private Spaces attachment mirror
- `app/documents.py`: embedded PDF-quote text extraction feeding synthesis
- `app/inference.py`: bounded Kimi response synthesis and reply drafting
- `app/discovery.py`: public venue website discovery

Older Sheet-first or experimental analysis paths—including `app/workflow.py`,
`app/agent.py`, and the `/analysis` surface—are not the canonical venue workflow.
Do not extend them unless the task explicitly concerns legacy cleanup.

## Change standard

Preserve the product invariants in `docs/PRODUCT_BRIEF.md`, add focused tests,
run `.venv/bin/python -m pytest -q`, and document any production configuration
change without committing credential values.
