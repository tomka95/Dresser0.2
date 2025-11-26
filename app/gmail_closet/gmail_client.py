"""Gmail client using IMAP for MVP implementation.

NOTE: This uses IMAP with app passwords for MVP/local development.
In production, this should be replaced with OAuth2-based Gmail API.
"""

import email
import imaplib
import logging
from datetime import datetime
from email.header import decode_header
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from .config import EXCLUDED_FOLDERS, IMAP_PORT, IMAP_SERVER, PURCHASE_SEARCH_TERMS
from .models import EmailMetadata

logger = logging.getLogger("dresser.gmail")
logger.setLevel(logging.INFO)


def decode_mime_words(s: str) -> str:
    """Decode MIME-encoded header values."""
    if not s:
        return ""
    decoded_parts = decode_header(s)
    decoded_string = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            if encoding:
                decoded_string += part.decode(encoding)
            else:
                decoded_string += part.decode("utf-8", errors="ignore")
        else:
            decoded_string += part
    return decoded_string


def extract_text_from_email(msg: email.message.Message) -> str:
    """Extract plain text from an email message, handling both text and HTML."""
    text_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        text_parts.append(payload.decode("utf-8", errors="ignore"))
                    except (UnicodeDecodeError, AttributeError):
                        pass
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        html_parts.append(payload.decode("utf-8", errors="ignore"))
                    except (UnicodeDecodeError, AttributeError):
                        pass
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                if content_type == "text/plain":
                    text_parts.append(payload.decode("utf-8", errors="ignore"))
                elif content_type == "text/html":
                    html_parts.append(payload.decode("utf-8", errors="ignore"))
            except (UnicodeDecodeError, AttributeError):
                pass

    # Prefer plain text, but fall back to HTML if needed
    if text_parts:
        return "\n".join(text_parts)

    if html_parts:
        # Use BeautifulSoup to extract text from HTML
        combined_html = "\n".join(html_parts)
        soup = BeautifulSoup(combined_html, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    return ""


class GmailClient:
    """IMAP-based Gmail client for MVP.

    SECURITY NOTE:
    - This uses IMAP with app passwords for MVP/local development.
    - In production, this must be replaced with OAuth2-based Gmail API.
    - Credentials are only used in-memory and never stored.
    """

    def __init__(self, email: str, app_password: str):
        """Initialize Gmail client with email and app password.

        Args:
            email: Gmail email address.
            app_password: Gmail App Password (not regular password).
        """
        self.email = email
        self.app_password = app_password
        self.imap: Optional[imaplib.IMAP4_SSL] = None

    def __enter__(self) -> "GmailClient":
        """Context manager entry: connect to Gmail."""
        self.imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        self.imap.login(self.email, self.app_password)

        # TODO: Remove this debug log before production.
        logger.info(f"Connected to Gmail as {self.email}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: close connection."""
        if self.imap:
            try:
                self.imap.close()
            except Exception:
                pass
            try:
                self.imap.logout()
            except Exception:
                pass
            self.imap = None

    def iter_purchase_like_messages(
        self, since: datetime
    ) -> Iterable[tuple[EmailMetadata, str]]:
        """Yield tuples of (EmailMetadata, raw_body_text) for purchase-like emails.

        Searches for emails that might be purchase/receipt emails using IMAP search.
        Ignores Spam/Trash folders.

        Args:
            since: Only search emails since this datetime.

        Yields:
            Tuples of (EmailMetadata, plain_text_body) for each matching email.
        """
        if not self.imap:
            raise RuntimeError("GmailClient must be used as a context manager")

        # Select INBOX
        status, _ = self.imap.select("INBOX")
        if status != "OK":
            raise RuntimeError(f"Failed to select INBOX: {status}")

        # Build search query using only SINCE date (for debugging, be generous)
        since_str = since.strftime("%d-%b-%Y")
        search_query = f'SINCE {since_str}'

        status, message_ids = self.imap.search(None, search_query)
        if status == "OK" and message_ids and message_ids[0]:
            all_message_ids = set(message_ids[0].decode().split())
        else:
            all_message_ids = set()

        # TODO: Remove this debug log before production.
        logger.info(f"Found {len(all_message_ids)} messages since {since_str}")

        # Fetch and parse each message
        for msg_id in all_message_ids:
            try:
                status, msg_data = self.imap.fetch(msg_id, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Extract metadata
                subject = decode_mime_words(msg.get("Subject", ""))
                sender = decode_mime_words(msg.get("From", ""))
                # msg_id may already be a string, so we must not call .decode() on it.
                fallback_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                message_id = msg.get("Message-ID", fallback_id)
                thread_id = msg.get("Thread-ID", message_id)

                # Parse date
                date_str = msg.get("Date", "")
                sent_at = datetime.utcnow()  # fallback
                try:
                    date_tuple = email.utils.parsedate_tz(date_str)
                    if date_tuple:
                        timestamp = email.utils.mktime_tz(date_tuple)
                        sent_at = datetime.fromtimestamp(timestamp)
                except (ValueError, TypeError):
                    pass

                # Extract body text
                body_text = extract_text_from_email(msg)

                # Get snippet (first 200 chars of body)
                snippet = body_text[:200] if body_text else None

                metadata = EmailMetadata(
                    message_id=message_id,
                    thread_id=thread_id,
                    subject=subject,
                    sender=sender,
                    sent_at=sent_at,
                    snippet=snippet,
                    labels=[],  # IMAP doesn't easily provide labels
                )

                yield (metadata, body_text)

            except Exception as e:
                # Skip messages that fail to parse
                continue

