"""Pydantic models for the Gmail token seam.

Trimmed in phase 3a: the old regex pipeline's models (GmailCredentials, Item,
ClothingPurchase) were deleted along with that pipeline. Only EmailMetadata
remains -- it is the return shape of GmailOAuthClient.iter_purchase_like_messages
and the one model the kept token-seam client still depends on. The 3b rebuild
will introduce its own typed candidate models (see ingest_candidates).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class EmailMetadata(BaseModel):
    """Metadata extracted from an email message."""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    sent_at: datetime
    snippet: Optional[str] = None
    labels: List[str] = []
