"""Email-TYPE gate (fix/receipt-email-type-gate): prove the layered order-vs-ad classifier
rejects marketing / price-drop / abandoned-cart mail WITHOUT dropping genuine receipts.

Layers under test:
  A  Tier-0 query          -> excludes Gmail Promotions at the source
  B  Tier-1 filter         -> promotions-label + ad-subject rejects (fire even WITH a price)
  C  cheap-LLM classifier  -> ambiguous residue only ("Your order is waiting"), fail-open
  D  extractor backstop    -> stage only when is_purchase AND is_clothing AND items

The hard guardrail — NEVER drop a genuine order confirmation — is asserted by the measurement
corpus at the bottom (real-receipt false-negative count MUST be 0).
"""
from __future__ import annotations

import base64
import types as _pytypes
import uuid

import pytest

import app.gmail_closet.extraction_service as ES
from app.core.config import settings
from app.gmail_closet import email_type_classifier as C
from app.gmail_closet.extraction_schema import ClosetCategory, ExtractedItem, ExtractedReceipt
from app.gmail_closet.extractor import ExtractionOutcome
from app.gmail_closet.fetch_service import _FIELDS_GET, _build_query
from app.gmail_closet.receipt_filter import is_ambiguous_type, passes_tier1_filter
from datetime import datetime

# Senders (all resolve to allow-listed retail domains after subdomain peeling).
LULU = "lululemon <hello@e.lululemon.com>"
NIKE = "Nike <news@email.nike.com>"
ASOS = "ASOS <no-reply@asos.com>"
UNKNOWN = "Foo Shop <sales@shop.example>"


# ===========================================================================
# Layer A — Tier-0 query excludes Promotions (source-level cost win)
# ===========================================================================

def test_tier0_query_excludes_promotions_but_keeps_or_branches():
    q = _build_query(datetime(2025, 1, 1))
    assert "-category:promotions" in q                 # ads never fetched
    assert "category:purchases" in q                   # OR-branches preserved
    assert "from:(" in q
    assert "subject:(" in q


def test_field_mask_now_fetches_labels_and_snippet():
    # Layer B needs labelIds; Layer C needs snippet. Both were previously omitted.
    assert "labelIds" in _FIELDS_GET
    assert "snippet" in _FIELDS_GET


# ===========================================================================
# Layer B — Tier-1 email-TYPE rejects
# ===========================================================================

def test_ad_with_price_is_rejected_THE_INVERSION_FIX():
    # Abandoned-cart ad that CARRIES a price. Previously kept (price disabled the marketing
    # filter, then known_retailer/price short-circuited to keep). Now rejected on subject.
    kept, reason = passes_tier1_filter(
        LULU, "Price drop on your carted items", "Define Jacket $99 — shop now", labels=[]
    )
    assert kept is False
    assert reason == "ad_subject"


def test_promotions_labeled_is_rejected():
    kept, reason = passes_tier1_filter(
        NIKE, "This week at Nike", "check out what's new", labels=["CATEGORY_PROMOTIONS"]
    )
    assert kept is False
    assert reason == "promotions_category"


def test_promotions_plus_purchases_is_not_rejected_by_label_rule():
    # Genuine receipt Gmail dual-labels must NOT be dropped by the promotions rule.
    kept, reason = passes_tier1_filter(
        ASOS, "Order confirmation", "Order #55231 total $99", labels=["CATEGORY_PROMOTIONS", "CATEGORY_PURCHASES"]
    )
    assert kept is True
    assert reason == "order_number"


def test_known_retailer_promo_is_not_auto_kept():
    # Retailer demoted to a WEAK positive: a promo subject from a known brand is rejected,
    # no longer auto-kept on the sender domain alone.
    kept, reason = passes_tier1_filter(
        NIKE, "New arrivals just dropped", "fresh styles $80", labels=[]
    )
    assert kept is False
    assert reason == "ad_subject"


def test_percent_off_subject_is_rejected():
    kept, reason = passes_tier1_filter(NIKE, "UP TO 40% OFF everything", "$40 tees", labels=[])
    assert kept is False
    assert reason == "ad_subject"


def test_genuine_order_confirmation_with_price_is_KEPT():
    # The critical guardrail: a real receipt that contains a price survives.
    kept, reason = passes_tier1_filter(
        ASOS, "Order confirmation #12345", "Define Jacket — Total $99.00", labels=["CATEGORY_PURCHASES"]
    )
    assert kept is True


def test_updates_labeled_receipt_is_KEPT_not_restricted_to_purchases():
    # Gmail files many receipts under Updates, not Purchases — they must survive.
    kept, reason = passes_tier1_filter(
        ASOS, "Your order has shipped", "Order #987654 — $50 shipped", labels=["CATEGORY_UPDATES"]
    )
    assert kept is True
    assert reason == "order_number"


def test_order_number_in_subject_overrides_discount_mention():
    # A genuine receipt whose subject mentions a discount is NOT dropped (order# override).
    kept, reason = passes_tier1_filter(
        ASOS, "Order #123456 confirmed — 20% off applied", "Total $80", labels=[]
    )
    assert kept is True
    assert reason == "order_number"


def test_hebrew_receipt_with_price_is_KEPT():
    kept, _ = passes_tier1_filter(
        UNKNOWN, "אישור הזמנה", 'סה"כ לתשלום 250 ש"ח', labels=["CATEGORY_PURCHASES"]
    )
    assert kept is True


def test_backward_compatible_without_labels_arg():
    # Existing 3-arg callers (explain, older code) still work; labels default to none.
    kept, _ = passes_tier1_filter(ASOS, "Order confirmation #42000", "Total $10")
    assert kept is True


# ===========================================================================
# Ambiguity predicate — which emails reach Layer C
# ===========================================================================

def test_ambiguous_flags_your_order_is_waiting():
    # Retailer + order-ish subject + price + NO order number -> ambiguous (goes to LLM).
    assert is_ambiguous_type(NIKE, "Your order is waiting", "Grab your Air Max $120 now", []) is True


def test_not_ambiguous_when_order_number_present():
    assert is_ambiguous_type(ASOS, "Your order", "Order #12345 total $80", []) is False


def test_not_ambiguous_for_unknown_sender():
    assert is_ambiguous_type(UNKNOWN, "Your order is waiting", "$120", []) is False


# ===========================================================================
# Layer C — cheap classifier: verdict, disabled, fail-open
# ===========================================================================

class _Resp:
    def __init__(self, verdict): self.parsed = verdict; self.text = None


def _provider_returning(verdict):
    return _pytypes.SimpleNamespace(generate_structured=lambda **kw: _Resp(verdict))


def test_classifier_marketing_verdict_false(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_TYPE_CLASSIFIER_ENABLED", True)
    monkeypatch.setattr(C, "get_ai_provider",
                        lambda: _provider_returning(C._TypeVerdict(is_order_confirmation=False)))
    assert C.classify_is_order_confirmation(NIKE, "Your order is waiting", "come back") is False


def test_classifier_order_verdict_true(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_TYPE_CLASSIFIER_ENABLED", True)
    monkeypatch.setattr(C, "get_ai_provider",
                        lambda: _provider_returning(C._TypeVerdict(is_order_confirmation=True)))
    assert C.classify_is_order_confirmation(ASOS, "Your order", "thanks") is True


def test_classifier_disabled_keeps(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_TYPE_CLASSIFIER_ENABLED", False)
    # Should not even call the provider.
    monkeypatch.setattr(C, "get_ai_provider",
                        lambda: (_ for _ in ()).throw(AssertionError("must not call")))
    assert C.classify_is_order_confirmation(NIKE, "anything", "x") is True


def test_classifier_fails_open_on_error(monkeypatch):
    # An LLM hiccup must KEEP the email (never drop a possible receipt).
    def boom(**kw): raise RuntimeError("api down")
    monkeypatch.setattr(settings, "GMAIL_TYPE_CLASSIFIER_ENABLED", True)
    monkeypatch.setattr(C, "get_ai_provider",
                        lambda: _pytypes.SimpleNamespace(generate_structured=boom))
    assert C.classify_is_order_confirmation(NIKE, "Your order is waiting", "x") is True


# ===========================================================================
# Layer C wiring — extraction skips the full LLM call for a classified ad
# ===========================================================================

def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _raw(sender, subject, body, labels, snippet=""):
    return {
        "internalDate": "0",
        "labelIds": labels,
        "snippet": snippet,
        "payload": {
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
            "mimeType": "text/plain",
            "body": {"data": _b64(body)},
        },
    }


def test_fetch_and_extract_type_rejects_ambiguous_ad_without_extraction(monkeypatch):
    raw = _raw(NIKE, "Your order is waiting", "Grab your Air Max $120 now", [], snippet="come back")
    monkeypatch.setattr(ES, "_fetch_one", lambda c, t, m: raw)
    monkeypatch.setattr(ES, "classify_is_order_confirmation", lambda s, su, sn: False)

    called = {"extract": False}
    monkeypatch.setattr(ES, "extract_receipt", lambda **kw: called.__setitem__("extract", True))

    res = ES._fetch_and_extract(None, "tok", "m1")
    assert res.type_rejected is True
    assert res.outcome is None
    assert called["extract"] is False          # full extraction was SKIPPED (cost saved)


def test_fetch_and_extract_skips_classifier_for_clear_receipt(monkeypatch):
    raw = _raw(ASOS, "Order confirmation #12345", "Total $99", ["CATEGORY_PURCHASES"])
    monkeypatch.setattr(ES, "_fetch_one", lambda c, t, m: raw)
    monkeypatch.setattr(ES, "classify_is_order_confirmation",
                        lambda *a: (_ for _ in ()).throw(AssertionError("clear receipt must not be classified")))
    sentinel = ExtractionOutcome(
        receipt=ExtractedReceipt(is_purchase=True, is_clothing=True, items=[], overall_confidence=0.9),
        model="x", escalated=False, parse_failed=False, api_failed=False,
        input_tokens=1, output_tokens=1, est_cost_flash_lite=0.0, est_cost_realistic=0.0,
    )
    monkeypatch.setattr(ES, "extract_receipt", lambda **kw: sentinel)

    res = ES._fetch_and_extract(None, "tok", "m2")
    assert res.type_rejected is False
    assert res.outcome is sentinel


# ===========================================================================
# Layer D — staging gate consults is_purchase
# ===========================================================================

def _outcome(receipt):
    return ExtractionOutcome(
        receipt=receipt, model="x", escalated=False, parse_failed=False, api_failed=False,
        input_tokens=0, output_tokens=0, est_cost_flash_lite=0.0, est_cost_realistic=0.0,
    )


def _item():
    return ExtractedItem(name="Define Jacket", category=ClosetCategory.outerwear, unit_price=99.0)


def test_stage_skips_when_is_purchase_false(monkeypatch):
    # An ad the LLM correctly marks is_purchase=false stages NOTHING even though it named a
    # garment with a price (is_clothing=true, items present). db=None proves the gate returns
    # before any DB write.
    calls = []
    monkeypatch.setattr(ES, "_upsert_candidate", lambda db, vals: calls.append(vals))
    res = ES._MsgExtraction("m", _outcome(
        ExtractedReceipt(is_purchase=False, is_clothing=True, items=[_item()], overall_confidence=0.9)
    ), None)
    keys = ES._stage_message(None, user_id=uuid.uuid4(), sync_id=uuid.uuid4(), res=res)
    assert keys == []
    assert calls == []


def test_stage_skips_when_not_clothing():
    res = ES._MsgExtraction("m", _outcome(
        ExtractedReceipt(is_purchase=True, is_clothing=False, items=[_item()], overall_confidence=0.9)
    ), None)
    assert ES._stage_message(None, user_id=uuid.uuid4(), sync_id=uuid.uuid4(), res=res) == []


def test_stage_proceeds_for_genuine_clothing_purchase(monkeypatch):
    calls = []
    monkeypatch.setattr(ES, "_upsert_candidate", lambda db, vals: calls.append(vals))
    res = ES._MsgExtraction("m", _outcome(
        ExtractedReceipt(is_purchase=True, is_clothing=True, items=[_item()], overall_confidence=0.9)
    ), None)
    keys = ES._stage_message(None, user_id=uuid.uuid4(), sync_id=uuid.uuid4(), res=res)
    assert len(keys) == 1 and len(calls) == 1       # genuine purchase -> staged


# ===========================================================================
# MEASUREMENT — representative corpus. HARD gate: real-receipt FN count == 0.
# ===========================================================================
# (case_id, kind, sender, subject, body, labels)  kind in {"ad","real"}
_CORPUS = [
    # --- ADs (expected DROP) ---
    ("ad-cart-price",    "ad", LULU, "Price drop on your carted items", "Define Jacket $99 shop now", []),
    ("ad-just-dropped",  "ad", NIKE, "All New Just Dropped!", "fresh $59 tees", ["CATEGORY_PROMOTIONS"]),
    ("ad-last-chance",   "ad", LULU, "Last chance to claim your cart", "you left $120 behind", []),
    ("ad-40-off",        "ad", NIKE, "UP TO 40% OFF", "sitewide $40", []),
    ("ad-advertisement", "ad", LULU, "Advertisement | Price drop inside", "was $150 now $99", ["CATEGORY_PROMOTIONS"]),
    ("ad-new-arrivals",  "ad", NIKE, "New arrivals just dropped", "$80 styles", []),
    ("ad-promo-label",   "ad", NIKE, "This week at Nike", "check us out", ["CATEGORY_PROMOTIONS"]),
    ("ad-back-in-stock", "ad", LULU, "Back in stock: the Align legging", "$98 grab it", []),
    ("ad-recommended",   "ad", NIKE, "Recommended for you", "picks from $60", []),
    # --- REAL receipts (expected KEEP — FN MUST be 0) ---
    ("real-conf-price",  "real", ASOS, "Order confirmation #12345", "Define Jacket Total $99.00", ["CATEGORY_PURCHASES"]),
    ("real-shipped-upd", "real", ASOS, "Your order has shipped", "Order #987654 $50 shipped", ["CATEGORY_UPDATES"]),
    ("real-dual-label",  "real", ASOS, "Order confirmation", "Order #55231 total $99", ["CATEGORY_PROMOTIONS", "CATEGORY_PURCHASES"]),
    ("real-discount-sub","real", ASOS, "Order #123456 confirmed — 20% off applied", "Total $80", []),
    ("real-hebrew",      "real", UNKNOWN, "אישור הזמנה", 'מספר הזמנה 4471 סה"כ 250 ש"ח', ["CATEGORY_PURCHASES"]),
    ("real-unknown-ord", "real", UNKNOWN, "Your receipt", "Order #55123 total $30", []),
    ("real-retailer-rcpt","real", ASOS, "Thank you for your order", "Order #778812 — $145 total", ["CATEGORY_PURCHASES"]),
]


def test_measurement_corpus_rejects_ads_and_keeps_every_receipt(capsys):
    ads = [c for c in _CORPUS if c[1] == "ad"]
    reals = [c for c in _CORPUS if c[1] == "real"]

    ad_rejected = ad_leaked = 0
    real_kept = real_dropped = 0
    dropped_receipts = []

    for cid, kind, sender, subject, body, labels in _CORPUS:
        kept, reason = passes_tier1_filter(sender, subject, body, labels)
        if kind == "ad":
            if kept:
                ad_leaked += 1
            else:
                ad_rejected += 1
        else:
            if kept:
                real_kept += 1
            else:
                real_dropped += 1
                dropped_receipts.append((cid, reason))

    print("\n=== Tier-1 email-TYPE gate — measurement (deterministic corpus) ===")
    print(f"ADS   : rejected {ad_rejected}/{len(ads)}  leaked {ad_leaked}")
    print(f"REAL  : kept     {real_kept}/{len(reals)}  DROPPED(FN) {real_dropped}")
    if dropped_receipts:
        print(f"  !! false-negatives: {dropped_receipts}")

    # HARD GUARDRAIL: not one genuine receipt may be dropped.
    assert real_dropped == 0, f"dropped genuine receipts: {dropped_receipts}"
    # Every deterministic ad in the corpus is rejected by Tier-1 alone.
    assert ad_leaked == 0, f"ads leaked past Tier-1: {ad_leaked}"
