"""Main pipeline that ties together Gmail scanning and clothing extraction.

This version keeps the external behavior the same (Gmail email + app password in,
List[Item] out) but replaces the old LLM-based extraction with our internal
heuristic parser.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Tuple

from .config import MAX_YEARS_TO_SCAN
from .filters import is_potential_clothing_email
from .gmail_client import GmailClient
from .models import EmailMetadata, GmailCredentials, Item
from app.services.email_smart_search import Email
from app.services.clothing_receipt_parser import parse_clothing_items_from_email


def _calculate_since(max_years: int | None) -> datetime:
    """Return the datetime to use as the lower bound when scanning emails."""
    years = max_years if max_years is not None else MAX_YEARS_TO_SCAN
    if years <= 0:
        years = 1
    # Rough conversion from years to days is enough for this use case.
    return datetime.utcnow() - timedelta(days=365 * years)


def _iter_candidate_emails(
    creds: GmailCredentials,
    since: datetime,
) -> Iterable[Tuple[EmailMetadata, str]]:
    """Yield (metadata, plain_text_body) for Gmail messages worth considering.

    Uses GmailClient to fetch messages since ``since`` and then applies
    is_potential_clothing_email to discard obviously irrelevant receipts.
    """
    with GmailClient(email=creds.email, app_password=creds.app_password) as client:
        for metadata, body_text in client.iter_purchase_like_messages(since=since):
            if not is_potential_clothing_email(metadata, body_text):
                continue
            yield metadata, body_text


async def extract_items_from_gmail(
    creds: GmailCredentials,
    max_years: int | None = None,
) -> List[Item]:
    """Connect to Gmail, scan purchase-like clothing emails, and return items.

    Flow:
        1. Compute ``since`` based on max_years (or MAX_YEARS_TO_SCAN).
        2. Use GmailClient to iterate purchase-like emails since that date.
        3. Filter further with is_potential_clothing_email.
        4. Wrap each email as Email (our internal dataclass).
        5. Parse clothing items with parse_clothing_items_from_email.
        6. Map ParsedClothingItem → Item and deduplicate.

    Args:
        creds: Gmail email + app password for IMAP access.
        max_years: Optional override for how far back to scan.

    Returns:
        A list of deduplicated Item objects representing clothing purchases.
    """
    since = _calculate_since(max_years)
    raw_items: List[Item] = []

    for metadata, body_text in _iter_candidate_emails(creds, since):
        email_obj = Email(
            id=metadata.message_id,
            subject=metadata.subject or "",
            body=body_text or "",
            sender=metadata.sender,
            date=metadata.sent_at.isoformat() if metadata.sent_at else None,
        )

        parsed_clothing_items = parse_clothing_items_from_email(email_obj)
        for parsed in parsed_clothing_items:
            name = parsed.product_name or parsed.category or "Clothing item"
            raw_items.append(
                Item(
                    name=name,
                    store=parsed.store,
                    price=parsed.price,
                    image=parsed.image_alt,
                )
            )

    # Deduplicate items by (name, store, price)
    unique: dict[tuple[str, str, float | None], Item] = {}
    for item in raw_items:
        key = (
            item.name.lower().strip(),
            (item.store or "").lower().strip(),
            item.price,
        )
        if key not in unique:
            unique[key] = item

    return list(unique.values())
