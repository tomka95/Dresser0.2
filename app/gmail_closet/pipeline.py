"""Main pipeline that ties together Gmail scanning and clothing extraction."""

import asyncio
from datetime import datetime, timedelta
from typing import List

from .config import MAX_CONCURRENT_EXTRACTIONS, MAX_YEARS_TO_SCAN
from .filters import is_potential_clothing_email
from .gmail_client import GmailClient
from .llm_extractor import extract_clothing_purchase_from_email
from .models import GmailCredentials, Item


async def extract_items_from_gmail(
    creds: GmailCredentials,
    max_years: int = MAX_YEARS_TO_SCAN,
) -> List[Item]:
    """Connect to Gmail, scan purchase-like emails, and return clothing items.

    This function:
    1. Connects to Gmail using the provided credentials
    2. Searches for purchase/receipt emails
    3. Filters emails that might contain clothing purchases
    4. Uses LLM to extract clothing items from filtered emails
    5. Returns a deduplicated list of Item objects

    Args:
        creds: Gmail credentials (email + app_password).
        max_years: Maximum number of years to look back (default from config).

    Returns:
        List of Item objects representing clothing/accessory purchases.
    """
    since = datetime.utcnow() - timedelta(days=365 * max_years)
    items: List[Item] = []

    # Semaphore to limit concurrent LLM calls
    sem = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)

    async def process_email(metadata, body_text):
        """Process a single email: filter and extract if applicable."""
        # First, apply cheap deterministic filter
        if not is_potential_clothing_email(metadata, body_text):
            return

        # Then, use LLM to extract (with concurrency limit)
        async with sem:
            purchase = await extract_clothing_purchase_from_email(metadata, body_text)

        if purchase:
            items.extend(purchase.items)

    tasks = []

    # Connect to Gmail and process emails
    with GmailClient(creds.email, creds.app_password) as client:
        import logging

        logger = logging.getLogger("dresser.gmail")

        # Count how many total purchase-like emails Gmail returned
        all_messages = list(client.iter_purchase_like_messages(since=since))
        logger.info(f"Fetched {len(all_messages)} emails from Gmail matching date criteria.")

        # Now apply the subject-based filter and log how many remain
        filtered_messages = []
        for metadata, body_text in all_messages:
            if is_potential_clothing_email(metadata, body_text):
                filtered_messages.append((metadata, body_text))

        logger.info(f"{len(filtered_messages)} emails passed subject-based purchase filter.")

        # Create tasks
        for metadata, body_text in filtered_messages:
            tasks.append(asyncio.create_task(process_email(metadata, body_text)))

    # Wait for all tasks to complete
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Deduplicate items by (name, store, price)
    unique = {}
    for item in items:
        key = (
            item.name.lower().strip(),
            (item.store or "").lower().strip(),
            item.price,
        )
        if key not in unique:
            unique[key] = item

    return list(unique.values())

