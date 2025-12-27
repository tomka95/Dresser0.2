"""Gmail OAuth client using Gmail REST API.

Provides the same interface as GmailClient but uses OAuth tokens.
"""

import base64
import logging
from datetime import datetime
from email.header import decode_header
from typing import Iterable, Optional, Tuple

from bs4 import BeautifulSoup
from googleapiclient.discovery import Resource
from sqlalchemy.orm import Session

from app.models import GoogleAccount
from app.gmail_closet.gmail_oauth_service import get_gmail_client
from .models import EmailMetadata

logger = logging.getLogger(__name__)


def decode_mime_words(s: str) -> str:
    """Decode MIME-encoded header values.
    
    Gmail API headers may still be MIME-encoded (e.g., =?UTF-8?B?...?=).
    This function decodes them to plain text, matching the IMAP client behavior.
    """
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


class GmailOAuthClient:
    """OAuth-based Gmail client using Gmail REST API.
    
    Provides the same interface as the IMAP-based GmailClient but uses
    OAuth tokens stored in GoogleAccount.
    """

    def __init__(self, google_account: GoogleAccount, db: Session):
        """Initialize Gmail OAuth client.
        
        Args:
            google_account: GoogleAccount instance with OAuth tokens
            db: Database session for token refresh if needed
        """
        self.google_account = google_account
        self.db = db
        self.gmail: Optional[Resource] = None

    def __enter__(self) -> "GmailOAuthClient":
        """Context manager entry: create Gmail API client."""
        self.gmail = get_gmail_client(self.google_account, self.db)
        logger.info(f"Connected to Gmail API for user {self.google_account.user_id}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: cleanup."""
        self.gmail = None

    def iter_purchase_like_messages(
        self, since: datetime
    ) -> Iterable[Tuple[EmailMetadata, str]]:
        """Yield tuples of (EmailMetadata, raw_body_text) for purchase-like emails.
        
        Searches for emails using Gmail REST API. This method provides the same
        interface as the IMAP version but uses OAuth authentication.
        
        Args:
            since: Only search emails since this datetime.
            
        Yields:
            Tuples of (EmailMetadata, plain_text_body) for each matching email.
        """
        if not self.gmail:
            raise RuntimeError("GmailOAuthClient must be used as a context manager")

        # Convert datetime to Unix timestamp for Gmail API
        since_timestamp = int(since.timestamp())
        
        # Build search query
        # Using "after:" for date filtering
        # Could add "category:purchases" but being broad for now
        query = f"after:{since_timestamp}"
        
        try:
            # List messages matching the query
            results = self.gmail.users().messages().list(
                userId='me',
                q=query,
                maxResults=500  # Adjust as needed
            ).execute()
            
            messages = results.get('messages', [])

            # Fetch each message in detail
            for msg_ref in messages:
                try:
                    msg_id = msg_ref['id']
                    
                    # Get full message
                    message = self.gmail.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format='full'
                    ).execute()
                    
                    # Extract metadata and body
                    metadata, body_text = self._parse_gmail_message(message)
                    
                    # TODO: Remove this debug logging
                    
                    yield (metadata, body_text)
                    
                except Exception as e:
                    logger.warning(f"Failed to fetch/parse message {msg_id}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Gmail API error: {e}")
            raise

    def _parse_gmail_message(self, message: dict) -> Tuple[EmailMetadata, str]:
        """Parse a Gmail API message into EmailMetadata and body text.
        
        Args:
            message: Gmail API message dict
            
        Returns:
            Tuple of (EmailMetadata, plain_text_body)
        """
        msg_id = message['id']
        thread_id = message.get('threadId', msg_id)
        snippet = message.get('snippet', '')
        
        # Extract headers and decode MIME-encoded values (same as IMAP version)
        headers = {h['name']: h['value'] for h in message['payload'].get('headers', [])}
        subject = decode_mime_words(headers.get('Subject', ''))
        sender = decode_mime_words(headers.get('From', ''))
        
        # Parse date
        internal_date_ms = int(message.get('internalDate', 0))
        sent_at = datetime.fromtimestamp(internal_date_ms / 1000) if internal_date_ms else datetime.utcnow()
        
        # Get labels (Gmail categories)
        labels = message.get('labelIds', [])
        
        # Extract body text
        body_text = self._extract_body_text(message['payload'])
        
        metadata = EmailMetadata(
            message_id=msg_id,
            thread_id=thread_id,
            subject=subject,
            sender=sender,
            sent_at=sent_at,
            snippet=snippet,
            labels=labels,
        )
        
        return metadata, body_text

    def _extract_body_text(self, payload: dict) -> str:
        """Extract plain text body from Gmail message payload.
        
        Uses the same logic as extract_text_from_email from gmail_client.py:
        - Prefers text/plain parts
        - Falls back to text/html with BeautifulSoup extraction
        - Skips attachments
        
        Args:
            payload: Gmail message payload dict
            
        Returns:
            Plain text body
        """
        text_parts = []
        html_parts = []
        
        def extract_from_payload(payload_dict: dict):
            """Recursively extract text/html from Gmail API payload structure."""
            # If this part has a body directly
            if 'body' in payload_dict and 'data' in payload_dict['body']:
                mime_type = payload_dict.get('mimeType', '')
                data = payload_dict['body']['data']
                content_disposition = payload_dict.get('body', {}).get('attachmentId')
                
                # Skip attachments (if attachmentId is present, it's an attachment)
                if content_disposition:
                    return
                
                try:
                    decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    if mime_type == 'text/plain':
                        text_parts.append(decoded)
                    elif mime_type == 'text/html':
                        html_parts.append(decoded)
                except Exception:
                    pass
            
            # If this payload has parts (multipart message)
            if 'parts' in payload_dict:
                for part in payload_dict['parts']:
                    extract_from_payload(part)
        
        extract_from_payload(payload)
        
        # Prefer plain text, but fall back to HTML if needed (same as IMAP version)
        if text_parts:
            return "\n".join(text_parts)
        
        if html_parts:
            # Use BeautifulSoup to extract text from HTML (same as IMAP version)
            combined_html = "\n".join(html_parts)
            soup = BeautifulSoup(combined_html, "html.parser")
            return soupClothingItem.get_text(separator=" ", strip=True)
        
        return ""

