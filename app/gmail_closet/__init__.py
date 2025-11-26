"""Gmail clothing purchase extraction pipeline.

This package provides an isolated pipeline for connecting to Gmail,
scanning purchase/receipt emails, and extracting clothing & accessory items.

NOTE: This is an MVP implementation using IMAP with app passwords.
In production, this must be replaced with OAuth2-based Gmail API access.
"""

from .router import router

__all__ = ["router"]

