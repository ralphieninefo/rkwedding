# Product brief: Wedding Venue Control Center

This document is the product source of truth for humans and coding models.
When prior experiments or implementation details conflict with this brief,
preserve the outcome and safety rules described here.

## Product outcome

Help Kassia and Raphaël find and follow up with a wedding venue without manually
maintaining a spreadsheet or repeatedly searching Gmail.

The product should answer, at a glance:

1. Which venues are under consideration?
2. Which venues have been contacted, from which mailbox, and when?
3. Who replied, what did they say in English, and what did they quote?
4. Which venues need a reply or another action?
5. Where are the original conversation and documents?

This is a small private operational tool for one couple. It is not a generic
agent platform, a CRM product, or a multi-tenant application.

## People and accounts

- Kassia and Raphaël share one application login and the same venue database.
- `raphaelkassia2027@gmail.com` is the primary wedding mailbox and must send all
  new venue inquiries.
- Previously contacted venues may have threads in Raphaël's personal mailbox.
  Those historical threads remain valid and should still be ingested.
- A follow-up must be sent from the mailbox that owns the existing thread. Never
  silently move a reply to another account or create a disconnected thread.
- Connecting Gmail is an owner-only setup operation, separate from signing into
  the dashboard. Ordinary dashboard visits must not start OAuth again.

## The golden workflow

### Product surfaces

- **Dashboard:** the active correspondence list. It shows compact, actionable
  Gmail-derived state—who was contacted, the latest brief English summary, the
  current step, and controls to preview/reply or open the correct Gmail thread.
- **Venues:** the durable reference directory. Each venue shows its accumulated
  summary, contact/research details, pricing and capacity, correspondence
  provenance, and mirrored assets with **View** and **Open in Gmail** actions.

Both surfaces are database-backed views of the same records. Neither reads from
Google Sheets, and neither needs a live Gmail request in order to render.

### 1. Open the dashboard

The user signs into the control center and immediately sees the last committed
PostgreSQL state. Venue data remains visible through deploys, worker failures,
and temporary Gmail or model outages. The page may poll the app API for newer
database state, but opening it must not call Gmail or require **Check Gmail**.

### 2. Add and contact a venue

1. Click **Add venue**.
2. Paste the public venue URL.
3. The app discovers name, region/location, public email, website, and phone.
4. The user reviews and edits those fields.
5. Saving creates a visible **Draft** venue in PostgreSQL.
6. The user requests an inquiry preview.
7. The app shows the exact recipient, subject, and full Italian message.
8. Only an explicit confirmation sends it from the shared wedding mailbox.
9. Gmail IDs, owning account, timestamp, and **Sent** status are committed.

Discovering or saving a venue must never send an email implicitly.

### 3. Ingest replies automatically

Every 15 minutes, the scheduled App Platform job:

1. loads all explicitly connected Gmail accounts;
2. searches known venue addresses and tracked Gmail threads;
3. stores unseen inbound and outbound messages idempotently;
4. follows a known thread when venue staff reply from a different address;
5. mirrors new attachments into the private Spaces bucket;
6. asks Kimi for a concise English synthesis and structured price data;
7. validates and stores derived data in PostgreSQL; and
8. commits the successful refresh time.

The UI reads the resulting database state. A new reply may take about 15 minutes
to appear; manual sync is a recovery/diagnostic action, not the normal workflow.

### 4. Review a response

The dashboard emphasizes decision data rather than the complete raw message:

- venue name and region;
- date added and first inquiry date;
- latest response time;
- concise English synthesis;
- workflow status;
- estimated total price for 90 guests when supported by the response; and
- a clear next action.

The user can open the original thread in the correct Gmail account. The venue
detail page includes contact and research metadata plus a **Documents** section.
**View** opens a short-lived link to the private Spaces mirror; **Open in Gmail**
opens the authoritative source message.

### 5. Follow up

1. Click **Review & reply** on a venue that has responded.
2. See the response synthesis, recipient, subject, and proposed reply.
3. Edit the reply freely.
4. Explicitly confirm sending.
5. Send through the account and thread attached to the latest inbound message.
6. Store the outbound message and update the venue's status.

The application may prepare text but must not autonomously send, accept a quote,
book a viewing, sign a contract, or pay a deposit.

### 6. Add external research

Human research from Reddit, calls, referrals, or other sources belongs in a
clearly labeled research section with source type, source URL, contact, notes,
and update time. It must not be represented as an official venue response.

## Data ownership

| Information | Authority | Application behavior |
|---|---|---|
| Venue records, status, summaries, estimates, checkpoints | PostgreSQL | Drives both application pages. |
| Original conversations and attachments | Gmail | Remains the canonical communication record. |
| Convenient attachment copy | Private Spaces bucket | One bucket, logically partitioned with venue/message key prefixes. |
| English summaries and price fields | Kimi via DO Serverless Inference | Derived, validated, replaceable data with graceful fallback. |
| Public contact details | Venue website | Suggested for human review before saving. |

## Status semantics

Statuses describe the next meaningful stage, not merely whether a row exists:

- **Draft**: saved, but no verified outbound inquiry exists.
- **Sent**: an outbound inquiry exists and no later inbound response is known.
- **Responded / Quote received / Viewing offered / More info needed**: the latest
  meaningful message is inbound; a human should review it.
- **Responded to venue**: a later outbound follow-up exists after a response.
- **Unavailable**: the venue explicitly declined or lacks availability.
- **Existing conversation**: sending was blocked because Gmail already contained
  a matching conversation; reconciliation should attach it to the venue.

Status calculation must use message direction and timestamps and must survive
safe reprocessing of the same Gmail data.

## Security and reliability invariants

- App Platform containers contain no durable state.
- OAuth refreshable credentials live only in PostgreSQL; OAuth client secrets,
  database URLs, model keys, and Spaces keys are encrypted runtime variables.
- Only allowlisted Gmail addresses can be connected.
- Browser APIs never expose token JSON, full stored email bodies, Spaces object
  keys, or credential values.
- Spaces remains private; document access uses short-lived signed URLs after app
  authentication.
- Gmail message IDs and attachment source IDs provide idempotency.
- Partial Gmail, Kimi, or Spaces failures do not erase committed venue
  data or prevent the dashboard from loading.
- Gmail API rate limits and transient failures receive bounded retries and a
  useful user-facing error.

## Explicit non-goals

- No Google Pub/Sub requirement for this workload; scheduled polling is enough.
- No Google Sheets integration, spreadsheet trigger, import, or spreadsheet as
  backend database. Venue information is entered and maintained in the app.
- No autonomous email sending or AI-controlled business decisions.
- No bucket per venue.
- No OCR or vision processing by default. Users can inspect scanned documents.
- No need to move OAuth from testing to production merely to support the two
  explicitly allowed owners while testing remains workable.
- No premature multi-user roles, billing, generic agent framework, or TAM demo
  features that do not help select the wedding venue.

## Improvement priorities

Work in this order and keep each change independently testable:

1. **Operational clarity:** visible last successful sync, account ownership,
   worker/attachment failures, and an owner-only retry action.
2. **Conversation correctness:** robustly link historical and alternate-sender
   replies to the right venue, mailbox, and Gmail thread.
3. **Decision workflow:** explicit next-action and shortlist states, comparison
   of price/capacity/location, and visit planning.
4. **Document usability:** clear attachment metadata and safe backfill status;
   optionally extract embedded PDF text, while leaving scanned PDFs for review.
5. **Legacy cleanup:** remove or quarantine unused Sheet-first agent/analysis code
   after verifying no production route or test depends on it.

Do not add more infrastructure until a demonstrated product need cannot be met
by the existing FastAPI service, scheduled job, PostgreSQL database, private
Spaces bucket, Gmail API, and bounded Kimi extraction.

## Definition of done for a product change

A change is complete only when:

- it supports one of the golden workflows above;
- it preserves account/thread provenance and explicit-send behavior;
- database and API changes are backward compatible or migrated safely;
- success, empty, loading, and recoverable failure states are understandable;
- focused automated tests cover the new behavior;
- the full test suite passes; and
- deployment configuration and architecture documentation are updated without
  committing secrets.

## Prompt for another coding model

> Review this repository starting with `docs/PRODUCT_BRIEF.md`, `AGENTS.md`,
> `README.md`, and `docs/ARCHITECTURE.md`. Trace the active production path from
> the browser through FastAPI, PostgreSQL, the scheduled Gmail worker, Spaces,
> and Kimi. Do not assume older Sheet-first or agent prototype modules are
> canonical. Compare the implementation to every golden workflow and invariant
> in the product brief. Identify concrete gaps with file/line evidence, rank them
> by user impact and risk, and then implement only the highest-value bounded
> improvement that can be tested independently. Preserve explicit human review
> before every send, Gmail account/thread provenance, PostgreSQL as the app
> source of truth, private attachment storage, idempotent ingestion, and
> stateless App Platform runtimes. Run the full test suite and report what
> changed, what was verified, and what remains. Do not broaden this private
> wedding-planning tool into a generic platform.
