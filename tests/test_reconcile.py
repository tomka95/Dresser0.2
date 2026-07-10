"""reconcile.py — the deterministic Stage-2 gate. Pure unit tests, no DB, no LLM.

Locked Gate-1 decisions under test:
- admission = order-id association OR totals-reconcile; quarantine only for an
  order_confirmation with neither, plus the zero-lines invariant alarm
- kind routing incl. fulfillment-creates-needs_enrichment (false-negative guard)
- retargeting >=2-price rule ONLY for orderless lines; a genuine repurchase
  (same item, two order_confirmations, different prices) is NOT demoted
- mixed email: order lines admit while "complete the look" tiles demote, in ONE email
- enrichment join binds variant rows to named lines only when bidirectionally unique
"""
from __future__ import annotations

import pytest

from app.gmail_closet.extraction_schema import (
    ClosetCategory,
    EmailKind,
    OrderInfo,
    OrderLine,
    ReceiptDocument,
    make_content_key_v2,
)
from app.gmail_closet.reconcile import (
    REASON_MARKETING,
    REASON_NO_ORDER_EVIDENCE,
    REASON_QUARANTINE_NO_EVIDENCE,
    REASON_QUARANTINE_ZERO_LINES,
    REASON_RECOMMENDATION,
    REASON_RETARGETING,
    apply_retargeting_rule,
    enrichment_join,
    looks_like_variant_only,
    parse_variant,
    reconcile_message,
    totals_reconcile,
)


def _line(name, price=None, qty=1, size=None, color=None, section=None, line_total=None):
    return OrderLine(
        name=name, category=ClosetCategory.top, unit_price=price, qty=qty,
        size=size, color=color, section_evidence=section, line_total=line_total,
    )


def _doc(kind, *, order=None, lines=(), recs=(), returned=(), merchant="SHEIN",
         stated=None, partial=None):
    return ReceiptDocument(
        email_kind=kind, is_clothing=True, merchant=merchant, order=order,
        order_lines=list(lines), recommendation_lines=list(recs),
        returned_lines=list(returned), stated_item_count=stated,
        partial_listing_note=partial, overall_confidence=0.9,
    )


# ===========================================================================
# Variant parsing + variant-only detection
# ===========================================================================

@pytest.mark.parametrize("text,color,size", [
    ("Black-L", "black", "l"),
    ("Multicolor-M", "multicolor", "m"),
    ("Embroidery-one-size-Navy Blue", "embroidery navy blue", "one-size"),
    ("Multicolor-Light Pink-1pc", "multicolor light pink", None),
    ("Brown-XL", "brown", "xl"),
    ("1PCS-Blue", "blue", None),
    ("Silver-one-size", "silver", "one-size"),
])
def test_parse_variant(text, color, size):
    assert parse_variant(text) == (color, size)


def test_variant_only_detection():
    assert looks_like_variant_only("Black-L") is True
    assert looks_like_variant_only("Multicolor-Dark Green") is True
    assert looks_like_variant_only('Wunder Train HR Tight 25"') is False
    assert looks_like_variant_only("SHEIN EZwear Crew Neck Casual T-Shirt") is False


# ===========================================================================
# Totals reconciliation
# ===========================================================================

def test_totals_match_subtotal_within_tolerance():
    doc = _doc(EmailKind.order_confirmation,
               order=OrderInfo(subtotal=50.00),
               lines=[_line("A", 20.00), _line("B", 15.00), _line("C", 14.60)])
    assert totals_reconcile(doc) is True   # 49.60 vs 50.00, within max($1, 2%)


def test_totals_mismatch_fails():
    doc = _doc(EmailKind.order_confirmation,
               order=OrderInfo(subtotal=100.00),
               lines=[_line("A", 20.00)])
    assert totals_reconcile(doc) is False


def test_totals_derived_from_total_minus_shipping_tax():
    doc = _doc(EmailKind.order_confirmation,
               order=OrderInfo(total=57.50, shipping=5.00, tax=2.50),
               lines=[_line("A", 25.00), _line("B", 25.00)])
    assert totals_reconcile(doc) is True


def test_partial_listing_is_never_checkable():
    # SHEIN: "36 Item(s) shipped" but only 12 shown — math CANNOT gate admission.
    doc = _doc(EmailKind.shipping,
               order=OrderInfo(order_id="GSH1", subtotal=100.0),
               lines=[_line("Black-L", 5.0)], stated=36,
               partial="Show up to 12 items due to email length restrictions")
    assert totals_reconcile(doc) is None


def test_unpriced_lines_not_checkable():
    doc = _doc(EmailKind.order_confirmation,
               order=OrderInfo(subtotal=100.0), lines=[_line("A")])
    assert totals_reconcile(doc) is None


# ===========================================================================
# Kind routing + admission
# ===========================================================================

def test_confirmation_with_order_id_admits():
    doc = _doc(EmailKind.order_confirmation, order=OrderInfo(order_id="GSH11L45C0019HH"),
               lines=[_line("Tee", 10.0, section="Order Details")])
    d = reconcile_message("m1", doc)
    assert not d.quarantined
    assert len(d.admitted) == 1 and d.demoted == []
    assert d.admitted[0].provenance["order_evidence"] == "order_id:GSH11L45C0019HH"


def test_confirmation_via_totals_only_admits():
    doc = _doc(EmailKind.order_confirmation, order=OrderInfo(subtotal=10.0),
               lines=[_line("Tee", 10.0)])
    d = reconcile_message("m1", doc)
    assert len(d.admitted) == 1
    assert d.admitted[0].provenance["order_evidence"] == "totals_reconciled"


def test_confirmation_with_neither_quarantines():
    doc = _doc(EmailKind.order_confirmation, order=None, lines=[_line("Tee", 10.0)])
    d = reconcile_message("m1", doc)
    assert d.quarantined and d.quarantine_reason == REASON_QUARANTINE_NO_EVIDENCE
    assert d.admitted == [] and d.demoted == []


def test_confirmation_zero_lines_is_invariant_alarm():
    doc = _doc(EmailKind.order_confirmation, order=OrderInfo(order_id="X"), lines=[])
    d = reconcile_message("m1", doc)
    assert d.quarantined and d.quarantine_reason == REASON_QUARANTINE_ZERO_LINES


def test_shipping_with_order_id_creates_needs_enrichment():
    # The variant-garbage ship rows are REAL purchases — admitted, flagged.
    doc = _doc(EmailKind.shipping, order=OrderInfo(order_id="GSH1QN45C0005QX"),
               lines=[_line("Black-L", section="Items shipped:"),
                      _line("Multicolor-Blue", section="Items shipped:")],
               stated=32, partial="Show up to 12 items due to email length restrictions")
    d = reconcile_message("m1", doc)
    assert len(d.admitted) == 2 and d.demoted == [] and not d.quarantined
    assert all(ld.needs_enrichment for ld in d.admitted)


def test_shipping_without_order_evidence_demotes_not_drops():
    doc = _doc(EmailKind.shipping, order=None, lines=[_line("Black-L")])
    d = reconcile_message("m1", doc)
    assert d.admitted == []
    assert len(d.demoted) == 1 and d.demoted[0].reason == REASON_NO_ORDER_EVIDENCE


def test_marketing_demotes_everything_with_reason():
    doc = _doc(EmailKind.marketing,
               lines=[_line("Sneaky ordered-looking tee", 9.99)],
               recs=[_line("Crop top", 6.0, section="Recommended for you")])
    d = reconcile_message("m1", doc)
    assert d.admitted == []
    reasons = sorted(ld.reason for ld in d.demoted)
    assert reasons == [REASON_MARKETING, REASON_RECOMMENDATION]


def test_marketing_with_full_order_evidence_is_overridden():
    # Misclassification guard: order id + reconciling totals beats a 'marketing' verdict.
    doc = _doc(EmailKind.marketing, order=OrderInfo(order_id="A1", subtotal=10.0),
               lines=[_line("Tee", 10.0, section="Order Details")])
    d = reconcile_message("m1", doc)
    assert d.kind_overridden is True
    assert d.email_kind == "order_confirmation"
    assert len(d.admitted) == 1


def test_return_lines_ride_admitted_with_is_return():
    doc = _doc(EmailKind.return_or_refund, order=OrderInfo(order_id="A1"),
               returned=[_line("Tee", 10.0, size="L", color="black")])
    d = reconcile_message("m1", doc)
    assert len(d.admitted) == 1 and d.admitted[0].is_return is True
    # Same v2 key as the original purchase line -> staging flips is_return on it.
    assert d.admitted[0].content_key == make_content_key_v2("SHEIN", "A1", "Tee", "L", "black")


def test_mixed_email_order_lines_admit_and_recs_demote():
    # The live lululemon ship email: real order lines + a "complete the look" section.
    doc = _doc(EmailKind.shipping, merchant="lululemon",
               order=OrderInfo(order_id="c175923092447259"),
               lines=[_line('Wunder Train HR Tight 25"', size="8", color="Sequoia",
                            section="Your order")],
               recs=[_line("Everywhere Belt Bag", 38.0, section="COMPLETE THE LOOK")])
    d = reconcile_message("m1", doc)
    assert len(d.admitted) == 1 and d.admitted[0].needs_enrichment is False
    assert len(d.demoted) == 1 and d.demoted[0].reason == REASON_RECOMMENDATION


# ===========================================================================
# Retargeting rule (corpus-level)
# ===========================================================================

def _admitted_orderless(name, price, mid, kind=EmailKind.shipping):
    # Orderless-but-totals-reconciled: the only way an id-less line gets admitted.
    doc = _doc(kind, order=OrderInfo(subtotal=price), lines=[_line(name, price)])
    return reconcile_message(mid, doc)


def test_retargeting_two_prices_demotes():
    # Non-confirmation orderless lines at 2 prices = ad impression stream.
    d1 = _admitted_orderless("Ribbed Crop Top", 11.99, "m1")
    d2 = _admitted_orderless("Ribbed Crop Top", 18.67, "m2")
    n = apply_retargeting_rule([d1, d2])
    assert n == 2
    assert d1.admitted == [] and d1.demoted[0].reason == REASON_RETARGETING
    assert d2.admitted == [] and d2.demoted[0].reason == REASON_RETARGETING


def test_retargeting_same_price_does_not_demote():
    d1 = _admitted_orderless("Ribbed Crop Top", 11.99, "m1")
    d2 = _admitted_orderless("Ribbed Crop Top", 11.99, "m2")
    assert apply_retargeting_rule([d1, d2]) == 0
    assert len(d1.admitted) == 1 and len(d2.admitted) == 1


def test_retargeting_exempts_reconciled_orderless_confirmations():
    # LOCKED exemption: two orderless order_confirmations whose math reconciles are
    # genuine repeat purchases even at different prices — never demoted.
    d1 = _admitted_orderless("Ribbed Crop Top", 11.99, "m1", EmailKind.order_confirmation)
    d2 = _admitted_orderless("Ribbed Crop Top", 18.67, "m2", EmailKind.order_confirmation)
    assert apply_retargeting_rule([d1, d2]) == 0
    assert len(d1.admitted) == 1 and len(d2.admitted) == 1


def test_genuine_repurchase_across_two_orders_is_NOT_demoted():
    # LOCKED Gate-1 condition: same item, two different order_confirmations, two
    # different prices -> both stay admitted (order ids exempt them by construction).
    doc1 = _doc(EmailKind.order_confirmation, order=OrderInfo(order_id="ORD-1"),
                lines=[_line("Align Legging", 98.0, size="6")])
    doc2 = _doc(EmailKind.order_confirmation, order=OrderInfo(order_id="ORD-2"),
                lines=[_line("Align Legging", 79.0, size="6")])
    d1, d2 = reconcile_message("m1", doc1), reconcile_message("m2", doc2)
    assert apply_retargeting_rule([d1, d2]) == 0
    assert len(d1.admitted) == 1 and len(d2.admitted) == 1
    # AND they stay two distinct closet rows (key embeds the order id).
    assert d1.admitted[0].content_key != d2.admitted[0].content_key


# ===========================================================================
# Enrichment join (corpus-level)
# ===========================================================================

def _order_pair():
    confirm = _doc(EmailKind.order_confirmation, order=OrderInfo(order_id="GSH-9"),
                   lines=[_line("SHEIN EZwear Graphic Crew Tee", 8.0, size="L", color="Black",
                                section="Order Details"),
                          _line("MUSERA Pleated Wide Leg Pants", 14.0, size="M", color="Multicolor",
                                section="Order Details")])
    ship = _doc(EmailKind.shipping, order=OrderInfo(order_id="GSH-9"),
                lines=[_line("Black-L", section="Items shipped:"),
                       _line("Multicolor-M", section="Items shipped:")])
    return reconcile_message("mc", confirm), reconcile_message("ms", ship)


def test_enrichment_join_binds_unambiguous_variants():
    dc, ds = _order_pair()
    n = enrichment_join([dc, ds])
    assert n == 2
    by_name = {ld.line.name for ld in ds.admitted}
    assert by_name == {"SHEIN EZwear Graphic Crew Tee", "MUSERA Pleated Wide Leg Pants"}
    assert all(not ld.needs_enrichment for ld in ds.admitted)
    # Keys collapsed onto the named lines -> staging merges to ONE row per item.
    assert {ld.content_key for ld in ds.admitted} == {ld.content_key for ld in dc.admitted}


def test_enrichment_join_ambiguous_stays_flagged():
    # Two named lines share (Black, L) — the variant row must NOT guess.
    confirm = _doc(EmailKind.order_confirmation, order=OrderInfo(order_id="GSH-9"),
                   lines=[_line("Tee One", 8.0, size="L", color="Black"),
                          _line("Tee Two", 9.0, size="L", color="Black")])
    ship = _doc(EmailKind.shipping, order=OrderInfo(order_id="GSH-9"),
                lines=[_line("Black-L")])
    dc, ds = reconcile_message("mc", confirm), reconcile_message("ms", ship)
    assert enrichment_join([dc, ds]) == 0
    assert ds.admitted[0].needs_enrichment is True


def test_enrichment_join_containment_color_match():
    confirm = _doc(EmailKind.order_confirmation, merchant="lululemon",
                   order=OrderInfo(order_id="c1"),
                   lines=[_line("Dance Studio Mid-Rise Pant", 118.0, size="6",
                                color="True Navy")])
    ship = _doc(EmailKind.shipping, merchant="lululemon", order=OrderInfo(order_id="c1"),
                lines=[_line("Navy-6")])
    dc, ds = reconcile_message("mc", confirm), reconcile_message("ms", ship)
    assert enrichment_join([dc, ds]) == 1
    assert ds.admitted[0].line.name == "Dance Studio Mid-Rise Pant"
