"""Tier-1 filter vs REAL (PII-redacted) email bodies from the Gate-1 live probe.

These fixtures are the actual leak population that produced 561 candidates from 72
messages on the v1 pipeline. The deterministic Tier-1 layer alone must now reject
every marketing email in the set and keep every genuine order/fulfillment email —
before any LLM is involved. (The Stage-1/Stage-2 behavior on these same emails is
proven by the live dry-run report, which runs the real extractor.)
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.gmail_closet.receipt_filter import passes_tier1_filter

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "gmail"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _verdict(name: str):
    f = _load(name)
    return passes_tier1_filter(f["sender"], f["subject"], f["body"], f["labels"])


# --- Marketing population: each was KEPT by v1 (known_retailer / price_pattern) ---

@pytest.mark.parametrize("fixture,expected_reason", [
    ("shein_grid_marketing", "promotions_category"),        # 18-tile campaign grid
    ("shein_cart_reminder", "promotions_category"),         # "LAST CALL" cart retargeting
    ("shein_clearance_blast", "promotions_category"),       # the seen-2-5x cluster
    ("lulu_bestseller_tiles", "promotions_category"),       # 6-tile bestseller ad
    ("aliexpress_advertisement_cart", "promotions_category"),
    ("ebay_promo_reengagement", "promotions_category"),
    ("drmartens_order_waiting", "promotions_category"),     # abandoned-cart "order waiting"
])
def test_marketing_email_rejected_deterministically(fixture, expected_reason):
    kept, reason = _verdict(fixture)
    assert kept is False, f"{fixture}: leaked with reason={reason}"
    assert reason == expected_reason


# --- Real order population: ZERO false negatives allowed --------------------------

@pytest.mark.parametrize("fixture", [
    "shein_order_confirmation",       # GSH11L45C0019HH confirm (6 lines shown)
    "shein_ship_partial36",           # ship, 12-of-36 variant rows
    "lulu_order_chain_delivered",     # c175923092447259 delivered notice
    "lulu_ship_complete_the_look",    # ship WITH a "complete the look" rec section
])
def test_real_order_email_kept(fixture):
    kept, reason = _verdict(fixture)
    assert kept is True, f"{fixture}: DROPPED ({reason}) — false negative"


def test_aliexpress_ad_rejected_even_without_labels():
    # Belt-and-suspenders: even if Gmail's Promotions label were missing, the
    # "Advertisement |" subject prefix must reject it deterministically (Layer B).
    f = _load("aliexpress_advertisement_cart")
    kept, reason = passes_tier1_filter(f["sender"], f["subject"], f["body"], labels=[])
    assert kept is False
    assert reason == "ad_subject"
