"""LLM-based extraction of clothing purchases from emails."""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .models import ClothingPurchase, EmailMetadata, Item

# Load environment variables
load_dotenv()

# Initialize OpenAI client lazily
_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    """Get or create the OpenAI client instance."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment."
            )
        _client = AsyncOpenAI(api_key=api_key)
    return _client

SYSTEM_PROMPT = """
You are an assistant that reads online shopping emails and extracts ONLY clothing and fashion accessory purchases.

RULES:
- If the email is not about a clothing/fashion purchase, respond with JSON:
  {"is_clothing_purchase": false}
- If the email is about a purchase that mixes clothes and non-clothes,
  ONLY output the clothing/fashion accessories. Ignore everything else.

Clothing/fashion includes:
- Clothes, shoes, bags, belts, hats, scarves, gloves, jewelry, sportswear, underwear, etc.

It does NOT include:
- Electronics, books, groceries, furniture, utilities, flights, hotels, subscriptions, etc.

Your response MUST be valid JSON with this schema:

{
  "is_clothing_purchase": boolean,
  "order_id": string or null,
  "order_date": string or null,    // ISO 8601 date if possible
  "retailer": string or null,
  "items": [
    {
      "name": string,
      "store": string or null,
      "price": number or null
    }
  ]
}

Additional rules:
- Only include items where you can identify BOTH a product name and a price.
- If an item has no clear price, DO NOT include it in the items array.
- If there are no clothing/fashion items with both name and price, respond with:
  {"is_clothing_purchase": false}
"""


async def extract_clothing_purchase_from_email(
    metadata: EmailMetadata,
    body_text: str,
) -> Optional[ClothingPurchase]:
    """Use the LLM to decide if this email contains clothing/accessory items.

    If so, extract them as a ClothingPurchase.

    Args:
        metadata: Email metadata.
        body_text: Plain text body of the email.

    Returns:
        ClothingPurchase if clothing items are found, None otherwise.
    """
    user_content = f"""
Email subject: {metadata.subject}
From: {metadata.sender}
Sent at: {metadata.sent_at.isoformat()}

Email body:
{body_text}
"""

    try:
        client = get_openai_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",  # OpenAI model for JSON extraction
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        raw = response.choices[0].message.content
        if not raw:
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # If parsing fails, treat as no purchase
            return None

        if not data.get("is_clothing_purchase"):
            return None

        # Parse items
        items = []
        for item_data in data.get("items", []):
            name = item_data.get("name", "").strip()
            if not name:
                continue

            # Parse price if present
            price = item_data.get("price")
            if price is not None:
                try:
                    price = float(price)
                except (ValueError, TypeError):
                    price = None

            # We only keep items that have BOTH name and a valid price
            if price is None:
                continue

            items.append(
                Item(
                    name=name,
                    store=item_data.get("store"),
                    price=price,
                )
            )

        # If, after filtering, there are no items with both name and price, treat as no purchase
        if not items:
            return None

        # Parse order_date if present
        order_date = None
        order_date_str = data.get("order_date")
        if order_date_str:
            try:
                from datetime import datetime

                order_date = datetime.fromisoformat(order_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return ClothingPurchase(
            email=metadata,
            order_id=data.get("order_id"),
            order_date=order_date,
            retailer=data.get("retailer"),
            items=items,
        )

    except Exception:
        # On any error, return None (treat as no purchase)
        return None

