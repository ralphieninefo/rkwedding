"""Bounded event orchestration for Gmail replies and quote tracking."""

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr

from pydantic import SecretStr

from app.agent import analyze_event
from app.config import Settings
from app.documents import extract_pdf_text
from app.email_templates import OUTREACH_BODY, OUTREACH_SUBJECT
from app.gmail import GmailClient
from app.google_auth import get_google_access_token
from app.models import GmailEvent, GmailPushNotification, VenueOutreachEvent
from app.sheets import GoogleSheetsClient


ACKNOWLEDGEMENT = """Buongiorno,

grazie per averci inviato il preventivo e le informazioni. Li esamineremo con attenzione e vi ricontatteremo a breve se avremo domande.

Cordiali saluti,
Raphaël
"""

@dataclass(frozen=True)
class ProcessingResult:
    action: str
    processed_messages: int


@dataclass(frozen=True)
class OutreachResult:
    status: str
    gmail_id: str | None = None
    gmail_thread_id: str | None = None


class WeddingWorkflow:
    """Coordinates deterministic Google I/O around a bounded model decision."""

    def __init__(
        self,
        settings: Settings,
        gmail: GmailClient | None = None,
        sheets: GoogleSheetsClient | None = None,
    ) -> None:
        token = settings.google_access_token
        if not token or not settings.google_spreadsheet_id:
            raise ValueError("Google access token and spreadsheet ID are required.")
        access_token = token.get_secret_value()
        self.settings = settings
        self.gmail = gmail or GmailClient(access_token, settings.google_gmail_user_id)
        self.sheets = sheets or GoogleSheetsClient(
            access_token, settings.google_spreadsheet_id
        )

    @classmethod
    async def create(cls, settings: Settings) -> "WeddingWorkflow":
        """Build a workflow with a freshly resolved Google OAuth token."""
        access_token = await get_google_access_token(settings)
        if not settings.google_spreadsheet_id:
            raise ValueError("Google spreadsheet ID is required.")
        return cls(
            settings.model_copy(update={"google_access_token": SecretStr(access_token)})
        )

    async def process_new_venue(self, event: VenueOutreachEvent) -> OutreachResult:
        """Create one inquiry after a deterministic duplicate check."""
        existing = await self.gmail.search_message_ids(
            f"in:anywhere {{to:{event.email} from:{event.email}}}", max_results=1
        )
        if existing:
            await self.sheets.update_row(
                self.settings.google_venues_sheet,
                event.row_number,
                {"Status": "Duplicate skipped"},
            )
            return OutreachResult("duplicate_skipped")

        sent = await self.gmail.send_message(
            event.email, OUTREACH_SUBJECT, OUTREACH_BODY
        )
        updates = {
            "Status": "Sent",
            "Gmail Message ID": sent.message_id,
            "Gmail Thread ID": sent.thread_id,
            "Date Inquired": datetime.now(UTC).date().isoformat(),
        }
        await self.sheets.update_row(
            self.settings.google_venues_sheet,
            event.row_number,
            updates,
        )
        return OutreachResult("sent", sent.message_id, sent.thread_id)

    async def process_notification(
        self, notification: GmailPushNotification
    ) -> ProcessingResult:
        """Process Gmail changes once and advance the durable checkpoint last."""
        checkpoint_key = f"gmail_history_id:{notification.email_address.casefold()}"
        checkpoint = await self.sheets.get_state(
            self.settings.google_system_sheet, checkpoint_key
        )
        if not checkpoint:
            await self.sheets.set_state(
                self.settings.google_system_sheet,
                checkpoint_key,
                notification.history_id,
            )
            return ProcessingResult("baseline_saved", 0)

        message_ids, latest_history_id = await self.gmail.list_added_message_ids(
            checkpoint
        )
        processed = 0
        for message_id in message_ids:
            processed_key = f"gmail_message:{message_id}"
            if await self.sheets.get_state(
                self.settings.google_system_sheet, processed_key
            ):
                continue

            message = await self.gmail.get_message(message_id)
            sender_email = parseaddr(message.sender)[1].casefold()
            if not sender_email or sender_email == notification.email_address.casefold():
                await self._mark_processed(processed_key)
                continue

            venue = await self.sheets.find_row(
                self.settings.google_venues_sheet, "Email", sender_email
            )
            if not venue:
                await self._mark_processed(processed_key)
                continue

            thread = await self.gmail.get_thread(message.thread_id)
            source_parts = [thread.body]
            pdf_names: list[str] = []
            for attachment in message.attachments:
                if attachment.mime_type == "application/pdf" or attachment.filename.lower().endswith(".pdf"):
                    pdf_names.append(attachment.filename)
                    pdf_bytes = await self.gmail.get_attachment(attachment)
                    pdf_text = extract_pdf_text(pdf_bytes)
                    source_parts.append(
                        f"PDF {attachment.filename}:\n{pdf_text or '[scanned PDF: manual review required]'}"
                    )

            decision = await analyze_event(
                GmailEvent(
                    venue=venue.get("Venue", sender_email),
                    message="\n\n".join(part for part in source_parts if part),
                    thread_id=message.thread_id,
                )
            )
            now = datetime.now(UTC).isoformat()
            quote = decision.quote
            await self.sheets.update_row(
                self.settings.google_venues_sheet,
                int(venue["_row_number"]),
                {
                    "Status": decision.status,
                    "Quoted price": (
                        quote.total_price if quote else decision.quoted_price
                    ) or "",
                    "Currency": (quote.currency if quote else decision.currency) or "",
                    "Response Received": "Yes",
                    "Last Response": now,
                    "Gmail Thread ID": message.thread_id,
                    "Response Summary": "; ".join(decision.facts)
                    or decision.status,
                },
            )
            if decision.event_type == "quote_received":
                existing_quote = await self.sheets.find_row(
                    self.settings.google_quotes_sheet,
                    "Gmail message ID",
                    message.message_id,
                )
                if not existing_quote:
                    await self.sheets.append_row(
                        self.settings.google_quotes_sheet,
                        [
                            venue.get("Venue", sender_email),
                            now,
                            (quote.total_price if quote else decision.quoted_price) or "",
                            (quote.currency if quote else decision.currency) or "",
                            quote.guest_count if quote and quote.guest_count else "",
                            quote.price_basis if quote and quote.price_basis else "",
                            quote.taxes_included if quote and quote.taxes_included is not None else "",
                            "; ".join(quote.inclusions) if quote else "",
                            "; ".join(quote.exclusions) if quote else "",
                            "; ".join(pdf_names),
                            message.message_id,
                            message.thread_id,
                        ],
                    )
                if not await self.gmail.has_draft_in_thread(
                    message.thread_id, sender_email
                ):
                    await self.gmail.create_draft(
                        recipient=sender_email,
                        subject=(
                            message.subject
                            if message.subject.lower().startswith("re:")
                            else f"Re: {message.subject}"
                        ),
                        body=ACKNOWLEDGEMENT,
                        thread_id=message.thread_id,
                        in_reply_to=message.rfc_message_id,
                        references=message.references,
                    )

            await self._mark_processed(processed_key)
            processed += 1

        await self.sheets.set_state(
            self.settings.google_system_sheet, checkpoint_key, latest_history_id
        )
        return ProcessingResult("completed", processed)

    async def _mark_processed(self, key: str) -> None:
        await self.sheets.set_state(
            self.settings.google_system_sheet,
            key,
            datetime.now(UTC).isoformat(),
        )
