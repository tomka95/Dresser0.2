"""Pydantic models for Gmail clothing purchase extraction."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class GmailCredentials(BaseModel):
    """Gmail credentials for MVP/local development.

    SECURITY NOTE:
    - This is for MVP/local usage only.
    - In production, this must be replaced with OAuth2 tokens.
    - The app_password field is explicitly named to indicate it should be
      a Gmail App Password (not a regular password).
    - Credentials are only used in-memory and never stored.
    """

    email: EmailStr
    app_password: str  # Gmail App Password for MVP. In production: OAuth tokens.


class EmailMetadata(BaseModel):
    """Metadata extracted from an email message."""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    sent_at: datetime
    snippet: Optional[str] = None
    labels: List[str] = []


class Item(BaseModel):
    """A single clothing or accessory item from a purchase."""

    name: str  # e.g. "Black skinny jeans"
    store: Optional[str] = None  # e.g. "Zara"
    price: Optional[float] = None  # total price for this line item
    image: Optional[str] = None  # e.g. alt text or image identifier


class ClothingPurchase(BaseModel):
    """A complete clothing purchase extracted from an email."""

    email: EmailMetadata
    order_id: Optional[str] = None
    order_date: Optional[datetime] = None
    retailer: Optional[str] = None
    items: List[Item]

