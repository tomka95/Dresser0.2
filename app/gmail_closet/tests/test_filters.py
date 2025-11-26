"""Tests for email filtering logic."""

from datetime import datetime

import pytest

from app.gmail_closet.filters import is_potential_clothing_email
from app.gmail_closet.models import EmailMetadata


def test_clothing_email_with_keywords():
    """Test that emails with clothing keywords are identified."""
    metadata = EmailMetadata(
        message_id="test-1",
        thread_id="test-1",
        subject="Your order confirmation - jeans and t-shirt",
        sender="store@example.com",
        sent_at=datetime.utcnow(),
    )
    body = "Thank you for your purchase. You ordered: 1x Blue Jeans, 1x White T-shirt."

    assert is_potential_clothing_email(metadata, body) is True


def test_non_clothing_email():
    """Test that non-clothing emails are rejected."""
    metadata = EmailMetadata(
        message_id="test-2",
        thread_id="test-2",
        subject="Your flight confirmation",
        sender="airline@example.com",
        sent_at=datetime.utcnow(),
    )
    body = "Your flight from NYC to LAX has been confirmed. Thank you for booking with us."

    assert is_potential_clothing_email(metadata, body) is False


def test_mixed_purchase_email():
    """Test that emails with both clothing and non-clothing keywords are handled."""
    metadata = EmailMetadata(
        message_id="test-3",
        thread_id="test-3",
        subject="Your order confirmation",
        sender="store@example.com",
        sent_at=datetime.utcnow(),
    )
    # Email with many non-clothing keywords should be rejected
    body = (
        "Thank you for your purchase. "
        "You ordered: 1x Laptop, 1x Software subscription, 1x Flight ticket, "
        "1x Hotel booking, 1x Grocery delivery."
    )

    assert is_potential_clothing_email(metadata, body) is False


def test_clothing_email_with_accessories():
    """Test that accessory keywords are recognized."""
    metadata = EmailMetadata(
        message_id="test-4",
        thread_id="test-4",
        subject="Order shipped - handbag and belt",
        sender="fashion@example.com",
        sent_at=datetime.utcnow(),
    )
    body = "Your order has shipped: 1x Leather Handbag, 1x Brown Belt."

    assert is_potential_clothing_email(metadata, body) is True


def test_email_without_clothing_keywords():
    """Test that emails without clothing keywords are rejected."""
    metadata = EmailMetadata(
        message_id="test-5",
        thread_id="test-5",
        subject="Your invoice",
        sender="service@example.com",
        sent_at=datetime.utcnow(),
    )
    body = "Thank you for your payment. Invoice #12345 for consulting services."

    assert is_potential_clothing_email(metadata, body) is False

