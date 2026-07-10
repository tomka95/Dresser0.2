"""Deterministic Stage-2 reconciliation — THE single admit/demote/quarantine gate.

The Stage-1 extractor (extractor.py) reports each email's STRUCTURE as a typed
ReceiptDocument: email kind, order block, and per-line placement with section
evidence. This module — plain code, no LLM — owns every decision about what enters
the closet:

  ADMISSION RULE (Gate-1 locked): an order line is admitted when the email carries
  ORDER-ID ASSOCIATION *or* its lines TOTALS-RECONCILE against the order block
  (Σ line money ≈ subtotal within tolerance). SHEIN truncates its own emails
  ("Show up to 12 items due to email length restrictions"), so totals can never
  reconcile there — order-id association is the primary key of admission; totals
  are the secondary path for retailers that show no order number but do show math.

  KIND ROUTING: order_confirmation creates items. shipping / delivery /
  review_request enrich the same order's items — and when the confirmation was
  never ingested their lines CREATE items flagged needs_enrichment (the false-
  negative guard for variant-garbage fulfillment rows, which are real purchases).
  marketing creates nothing: every product line is demoted, never dropped.
  return_or_refund produces negative events matched by (order_id, size, color)
  with a fuzzy-name fallback.

  SAFETY: demote, never delete — every demotion carries a machine-readable reason.
  An order_confirmation that admits ZERO lines is an extraction failure, not an
  empty order: the email is QUARANTINED for re-extraction (invariant alarm).
  A `marketing` verdict that nonetheless carries an order id AND reconciling
  totals is overridden to order_confirmation (misclassification guard — the
  false-negative failure mode always wins ties).

  RETARGETING RULE: the same normalized name at >=2 distinct prices with NO order
  association is an ad impression stream, not a purchase — demoted automatically.
  Lines inside DIFFERENT order_confirmations (a genuine repurchase at a new price)
  are exempt: their keys carry order ids, so the rule never sees them.

Everything here is pure: no DB, no network, no clock. The extraction service and
the reprocess script both route through these functions so there is exactly ONE
implementation of the gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .extraction_schema import (
    EmailKind,
    OrderLine,
    ReceiptDocument,
    make_content_key_v2,
    normalize_name,
)

# ---------------------------------------------------------------------------
# Demotion / quarantine reason codes (machine-readable; stored verbatim).
# ---------------------------------------------------------------------------
REASON_RECOMMENDATION = "recommendation_tile"          # sat in a recommendation section
REASON_MARKETING = "marketing_email"                   # any product line in a marketing email
REASON_NO_ORDER_EVIDENCE = "no_order_evidence"         # order-ish line, but no order id and no reconciling totals
REASON_RETARGETING = "retargeting_multi_price"         # same name, >=2 prices, no order association
REASON_MERGED = "merged_duplicate"                     # variant row absorbed by its named line
REASON_NON_GARMENT = "non_clothing_variant"            # variant size is a physical dimension, not a garment size
REASON_QUARANTINE_ZERO_LINES = "order_confirmation_zero_lines"   # invariant alarm
REASON_QUARANTINE_NO_EVIDENCE = "order_confirmation_no_evidence" # neither order id nor totals

# Kinds whose order_lines belong to a real, already-placed order.
_FULFILLMENT_KINDS = (EmailKind.shipping, EmailKind.delivery, EmailKind.review_request)
_ORDER_KINDS = (EmailKind.order_confirmation,) + _FULFILLMENT_KINDS

# Totals tolerance: rounding + per-line discount allocation drift.
_TOL_ABS = 1.00      # currency units
_TOL_REL = 0.02      # 2%


# ---------------------------------------------------------------------------
# Variant parsing — "Black-L", "Embroidery-one-size-Navy Blue", "Multicolor-M".
# SHEIN fulfillment emails carry ONLY these strings; the enrichment join uses the
# parsed (color, size) to bind them back to the order-confirmation's named lines.
# ---------------------------------------------------------------------------

_SIZE_TOKEN_RE = re.compile(
    r"^(xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]xl|one[- ]?size|\d{1,2}(\.\d)?|\d{2,3}[a-f]?)$",
    re.IGNORECASE,
)
_PACK_TOKEN_RE = re.compile(r"^\d+\s*pcs?$", re.IGNORECASE)

# A garment size is never a physical dimension. "30x40cm Wood Framed" is a poster;
# nameless manifest rows carrying one are the order's NON-clothing items (their named
# lines were rightly omitted upstream, so no enrichment join will ever kill them).
_NON_GARMENT_SIZE_RE = re.compile(
    r"\d+\s*[x×]\s*\d+\s*(cm|mm|inch|in)\b|\bframed\b|\bunframed\b",
    re.IGNORECASE,
)


def looks_non_garment_variant(line: OrderLine) -> bool:
    """True when a (typically nameless) manifest row's size/name carries a physical
    dimension — a poster/frame/home item riding in a clothing order."""
    hay = f"{line.name or ''} {line.size or ''}"
    return bool(_NON_GARMENT_SIZE_RE.search(hay))

# Color / shade vocabulary used ONLY to judge "is this bare variant text": tokens
# here don't count as product-name words. Deliberately common-shades-only.
_COLOR_WORDS = frozenset((
    "black", "white", "blue", "navy", "green", "pink", "red", "brown", "silver",
    "gold", "gray", "grey", "beige", "cream", "ivory", "purple", "violet",
    "yellow", "orange", "khaki", "apricot", "burgundy", "maroon", "teal", "cyan",
    "multicolor", "multicolour", "multi", "dark", "light", "hot", "pale", "deep",
    "true", "dusty", "neon", "pastel", "size",
))


_LINE_NOISE_PREFIX_RE = re.compile(r"^\s*size\s*:\s*", re.IGNORECASE)
_LINE_NOISE_SUFFIX_RE = re.compile(r"\s*qty\s*:?\s*\d+\s*$", re.IGNORECASE)


def strip_line_noise(name: Optional[str]) -> str:
    """Drop SHEIN manifest furniture from a line name: a leading 'SIZE:' label and a
    trailing 'QTY: n'. 'SIZE: Brown QTY: 1' -> 'Brown', so the same physical item
    keyed from the ship email and the delivery notification collapses to ONE row."""
    if not name:
        return ""
    out = _LINE_NOISE_PREFIX_RE.sub("", name.strip())
    out = _LINE_NOISE_SUFFIX_RE.sub("", out)
    return out.strip()


def parse_variant(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split a bare variant string into (color, size); (None, None) when unparseable.

    Tokens split on '-' are classified: a size token (letter sizes, numerics,
    one-size) becomes the size; pack-count tokens ("1pc") are dropped; whatever
    remains, joined in order, is the color/descriptor. Ambiguity returns what was
    confidently found — a miss keeps the row needs_enrichment, never mis-binds it.
    """
    text = strip_line_noise(text)
    if not text:
        return None, None
    size: Optional[str] = None
    # "one-size" contains the split character — extract it before tokenizing.
    one_size = re.search(r"one[- ]?size", text, re.IGNORECASE)
    if one_size:
        size = "one-size"
        text = (text[:one_size.start()] + " " + text[one_size.end():]).strip(" -")
    tokens = [t.strip() for t in text.split("-") if t.strip()]
    color_parts: List[str] = []
    for tok in tokens:
        if size is None and _SIZE_TOKEN_RE.match(tok):
            size = tok.lower()
        elif _PACK_TOKEN_RE.match(tok):
            continue
        else:
            color_parts.append(tok)
    color = " ".join(color_parts).strip().lower() or None
    return color, size


def looks_like_variant_only(name: Optional[str]) -> bool:
    """True when a line's `name` is bare variant text, not a product name.

    Heuristic: short, no letter-run beyond color/size vocabulary — i.e. every token
    is a size / pack / single descriptor word. "Black-L" -> True; "Wunder Train HR
    Tight 25\"" -> False. Deliberately conservative: a false False just means an
    enrichable row keeps its (real) name; a false True only flags enrichment.
    """
    if not name:
        return True
    # DEFECT FIX (Gate-2 close-out): manifest furniture in the name ("SIZE: ..."
    # prefix / "QTY: n" suffix) IS the variant pattern — such a row is a
    # fulfillment-manifest string regardless of which email KIND rendered it
    # (a confirmation that rendered a line as variant text must not bypass the
    # generation exclusion). Checked BEFORE stripping, on the raw name.
    if _LINE_NOISE_PREFIX_RE.search(name) or _LINE_NOISE_SUFFIX_RE.search(name):
        return True
    stripped = strip_line_noise(name)
    if not stripped:
        return True
    if len(stripped) > 40:
        return False
    tokens = re.split(r"[-,/ ]+", stripped)
    wordy = [t for t in tokens if len(t) > 2 and not _SIZE_TOKEN_RE.match(t)
             and not _PACK_TOKEN_RE.match(t)
             and t.lower() not in _COLOR_WORDS]
    # <=1 non-color descriptor word ("Embroidery") = variant text; a real product
    # name has 2+ garment nouns ("Align High-Rise Short", "Graphic Crew Tee").
    return len(wordy) <= 1


# ---------------------------------------------------------------------------
# Totals reconciliation
# ---------------------------------------------------------------------------

def _line_money(line: OrderLine) -> Optional[float]:
    if line.line_total is not None:
        return float(line.line_total)
    if line.unit_price is not None:
        return float(line.unit_price) * max(1, line.qty or 1)
    return None


def totals_reconcile(doc: ReceiptDocument) -> Optional[bool]:
    """True/False when checkable; None when the email doesn't carry enough money data.

    Checks Σ(line money) against subtotal, and against the total re-derived from
    its parts (total - shipping - tax + discount) — either match passes. A partial
    listing (stated_item_count > shown lines, or an explicit truncation note) is
    NEVER checkable: the email itself says the list is incomplete.
    """
    order = doc.order
    if order is None:
        return None
    lines = doc.order_lines
    monies = [_line_money(l) for l in lines]
    if not monies or any(m is None for m in monies):
        return None
    if doc.partial_listing_note or (
        doc.stated_item_count is not None and doc.stated_item_count > len(lines)
    ):
        return None
    line_sum = sum(monies)  # type: ignore[arg-type]

    targets: List[float] = []
    if order.subtotal is not None:
        targets.append(float(order.subtotal))
    if order.total is not None:
        derived = float(order.total)
        derived -= float(order.shipping or 0.0)
        derived -= float(order.tax or 0.0)
        derived += float(order.discount or 0.0)
        targets.append(derived)
        targets.append(float(order.total))   # some receipts fold everything into total
    if not targets:
        return None

    for target in targets:
        if abs(line_sum - target) <= max(_TOL_ABS, _TOL_REL * abs(target)):
            return True
    return False


# ---------------------------------------------------------------------------
# Per-message reconciliation
# ---------------------------------------------------------------------------

@dataclass
class LineDecision:
    """One product line's fate, with everything the staging layer needs to persist."""
    line: OrderLine
    admitted: bool
    reason: Optional[str]            # demotion reason when admitted=False
    content_key: str
    needs_enrichment: bool
    is_return: bool
    provenance: Dict                 # {email_kind, section_evidence, order_evidence, ...}


@dataclass
class MessageDecision:
    """The reconcile verdict for one email."""
    message_id: str
    email_kind: str
    merchant: Optional[str]
    order_id: Optional[str]
    admitted: List[LineDecision] = field(default_factory=list)
    demoted: List[LineDecision] = field(default_factory=list)
    quarantined: bool = False
    quarantine_reason: Optional[str] = None
    kind_overridden: bool = False    # marketing verdict overridden by order evidence


def _effective_kind(doc: ReceiptDocument) -> Tuple[EmailKind, bool]:
    """Misclassification guard: order evidence beats a marketing/other verdict.

    A `marketing`/`other` document that nonetheless carries an order id AND
    reconciling totals is structurally an order confirmation — treat it as one.
    (False negatives are the failure mode to avoid; ads carry neither.)
    """
    kind = doc.email_kind
    if kind in (EmailKind.marketing, EmailKind.other):
        has_id = bool(doc.order and doc.order.order_id)
        if has_id and totals_reconcile(doc) is True:
            return EmailKind.order_confirmation, True
    return kind, False


def _order_evidence(doc: ReceiptDocument, reconciled: Optional[bool]) -> Optional[str]:
    if doc.order and doc.order.order_id:
        return f"order_id:{doc.order.order_id}"
    if reconciled is True:
        return "totals_reconciled"
    return None


def _mk_provenance(doc: ReceiptDocument, kind: EmailKind, line: OrderLine,
                   evidence: Optional[str], reconciled: Optional[bool]) -> Dict:
    return {
        "email_kind": kind.value,
        "section_evidence": line.section_evidence,
        "order_evidence": evidence,
        "reconciled": reconciled,
        "stated_item_count": doc.stated_item_count,
        "partial_listing": bool(doc.partial_listing_note),
    }


def _decide_line(doc: ReceiptDocument, kind: EmailKind, line: OrderLine, *,
                 admitted: bool, reason: Optional[str], evidence: Optional[str],
                 reconciled: Optional[bool], needs_enrichment: bool = False,
                 is_return: bool = False) -> LineDecision:
    order_id = doc.order.order_id if doc.order else None
    return LineDecision(
        line=line,
        admitted=admitted,
        reason=reason,
        content_key=make_content_key_v2(
            doc.merchant, order_id, strip_line_noise(line.name), line.size, line.color),
        needs_enrichment=needs_enrichment,
        is_return=is_return,
        provenance=_mk_provenance(doc, kind, line, evidence, reconciled),
    )


def reconcile_message(message_id: str, doc: ReceiptDocument) -> MessageDecision:
    """Route ONE email's document through the admission rules. Pure."""
    kind, overridden = _effective_kind(doc)
    reconciled = totals_reconcile(doc)
    evidence = _order_evidence(doc, reconciled)
    order_id = doc.order.order_id if doc.order else None

    out = MessageDecision(
        message_id=message_id,
        email_kind=kind.value,
        merchant=doc.merchant,
        order_id=order_id,
        kind_overridden=overridden,
    )

    # Recommendation tiles: demoted in EVERY kind — never purchases.
    for line in doc.recommendation_lines:
        out.demoted.append(_decide_line(
            doc, kind, line, admitted=False, reason=REASON_RECOMMENDATION,
            evidence=None, reconciled=reconciled))

    # Returned lines: negative events. They ride on the same content key so the
    # staging layer can flip is_return on the matching admitted row.
    for line in doc.returned_lines:
        out.admitted.append(_decide_line(
            doc, kind, line, admitted=True, reason=None, evidence=evidence,
            reconciled=reconciled, is_return=True))

    if kind == EmailKind.order_confirmation:
        if not doc.order_lines:
            # Invariant alarm: a confirmation that reconciles to zero lines is an
            # extraction failure — quarantine the email, never silently accept.
            out.quarantined = True
            out.quarantine_reason = REASON_QUARANTINE_ZERO_LINES
            return out
        if evidence is None:
            # Neither order id nor reconciling totals: quarantine for re-extraction.
            out.quarantined = True
            out.quarantine_reason = REASON_QUARANTINE_NO_EVIDENCE
            return out
        for line in doc.order_lines:
            if looks_non_garment_variant(line):
                out.demoted.append(_decide_line(
                    doc, kind, line, admitted=False, reason=REASON_NON_GARMENT,
                    evidence=evidence, reconciled=reconciled))
                continue
            out.admitted.append(_decide_line(
                doc, kind, line, admitted=True, reason=None, evidence=evidence,
                reconciled=reconciled,
                needs_enrichment=looks_like_variant_only(line.name)))
        return out

    if kind in _FULFILLMENT_KINDS:
        # Fulfillment lines are real purchases. With order evidence they admit —
        # creating needs_enrichment rows when the confirmation never showed the
        # name (the enrichment join clears the flag when it can bind them).
        for line in doc.order_lines:
            if evidence is not None and looks_non_garment_variant(line):
                out.demoted.append(_decide_line(
                    doc, kind, line, admitted=False, reason=REASON_NON_GARMENT,
                    evidence=evidence, reconciled=reconciled))
            elif evidence is not None:
                out.admitted.append(_decide_line(
                    doc, kind, line, admitted=True, reason=None, evidence=evidence,
                    reconciled=reconciled,
                    needs_enrichment=looks_like_variant_only(line.name)))
            else:
                out.demoted.append(_decide_line(
                    doc, kind, line, admitted=False, reason=REASON_NO_ORDER_EVIDENCE,
                    evidence=None, reconciled=reconciled))
        return out

    if kind == EmailKind.return_or_refund:
        # order_lines in a return email are the items being returned when the
        # model did not use returned_lines; treat them as negative events too.
        for line in doc.order_lines:
            out.admitted.append(_decide_line(
                doc, kind, line, admitted=True, reason=None, evidence=evidence,
                reconciled=reconciled, is_return=True))
        return out

    # marketing / other: every remaining product line is demoted, never dropped.
    for line in doc.order_lines:
        out.demoted.append(_decide_line(
            doc, kind, line, admitted=False, reason=REASON_MARKETING,
            evidence=None, reconciled=reconciled))
    return out


# ---------------------------------------------------------------------------
# Corpus-level passes (retargeting + enrichment join). Pure; used by the
# reprocess script directly and mirrored incrementally by the service.
# ---------------------------------------------------------------------------

def apply_retargeting_rule(decisions: List[MessageDecision]) -> int:
    """Demote orderless admitted lines whose normalized name appears at >=2
    distinct prices with no order association anywhere. Returns #lines demoted.

    Lines admitted under an order id are exempt BY CONSTRUCTION (a genuine
    repurchase in two different orders carries two order ids)."""
    orderless: Dict[str, List[Tuple[MessageDecision, LineDecision]]] = {}
    for md in decisions:
        for ld in md.admitted:
            if ld.is_return:
                continue
            evidence = ld.provenance.get("order_evidence") or ""
            if evidence.startswith("order_id:"):
                continue   # order-id association: exempt by construction
            if (ld.provenance.get("email_kind") == "order_confirmation"
                    and ld.provenance.get("reconciled") is True):
                # An orderless CONFIRMATION whose math reconciles is a real receipt —
                # two of them at different prices are a genuine repurchase, not ads
                # (locked Gate-1 exemption).
                continue
            orderless.setdefault(normalize_name(ld.line.name), []).append((md, ld))

    demoted = 0
    for name, entries in orderless.items():
        prices = {round(float(ld.line.unit_price), 2)
                  for _, ld in entries if ld.line.unit_price is not None}
        if len(prices) >= 2:
            for md, ld in entries:
                md.admitted.remove(ld)
                ld.admitted = False
                ld.reason = REASON_RETARGETING
                md.demoted.append(ld)
                demoted += 1
    return demoted


def enrichment_join(decisions: List[MessageDecision]) -> int:
    """Bind fulfillment variant rows to their order-confirmation named lines.

    Within one order_id: a needs_enrichment line whose parsed (color, size)
    matches EXACTLY ONE named (non-enrichment) admitted line — and that named
    line matches no other variant — takes the named line's product name/brand/
    category and clears needs_enrichment; its content key collapses onto the
    named line's key so staging merges them into one candidate. Ambiguous rows
    stay needs_enrichment. Returns #rows enriched.
    """
    by_order: Dict[Tuple[Optional[str], Optional[str]], List[LineDecision]] = {}
    for md in decisions:
        for ld in md.admitted:
            if md.order_id:
                by_order.setdefault((normalize_name(md.merchant), md.order_id), []).append(ld)

    enriched = 0
    for (_merchant, _oid), lines in by_order.items():
        named = [l for l in lines if not l.needs_enrichment and not l.is_return]
        variants = [l for l in lines if l.needs_enrichment and not l.is_return]
        if not named or not variants:
            continue

        def _named_sig(l: LineDecision) -> Tuple[Optional[str], Optional[str]]:
            return ((l.line.color or "").strip().lower() or None,
                    (l.line.size or "").strip().lower() or None)

        # Bidirectional unique match: variant -> exactly one named line AND that
        # named line -> exactly one variant. Anything else stays needs_enrichment.
        var_matches = {
            id(var): [n for n in named if _matches(_named_sig(n), _variant_sig(var))]
            for var in variants
            if _variant_sig(var) != (None, None)
        }
        claim_count: Dict[int, int] = {}
        for matches in var_matches.values():
            if len(matches) == 1:
                claim_count[id(matches[0])] = claim_count.get(id(matches[0]), 0) + 1

        for var in variants:
            matches = var_matches.get(id(var), [])
            if len(matches) != 1:
                continue
            target = matches[0]
            if claim_count.get(id(target), 0) != 1:
                continue   # two variants claim the same named line — ambiguous
            vcolor, vsize = _variant_sig(var)
            var.line.name = target.line.name
            var.line.brand = var.line.brand or target.line.brand
            var.line.category = target.line.category
            var.line.color = target.line.color or vcolor
            var.line.size = target.line.size or vsize
            var.needs_enrichment = False
            var.content_key = target.content_key   # collapse: staging merges the rows
            enriched += 1
    return enriched


def _variant_sig(v: LineDecision) -> Tuple[Optional[str], Optional[str]]:
    """The (color, size) a variant row knows — parsed from its name, preferring
    fields the extractor already split out."""
    vcolor, vsize = parse_variant(v.line.name)
    if v.line.color:
        vcolor = v.line.color.strip().lower() or vcolor
    if v.line.size:
        vsize = v.line.size.strip().lower() or vsize
    return vcolor, vsize


def _matches(named: Tuple[Optional[str], Optional[str]],
             variant: Tuple[Optional[str], Optional[str]]) -> bool:
    """(color, size) equality where the variant side may only know one of the two.

    Whatever the variant DOES know must match; a variant knowing neither never
    matches (guarded by the caller). Color comparison is containment-tolerant:
    'navy blue' matches 'True Navy Blue'."""
    ncolor, nsize = named
    vcolor, vsize = variant
    if vsize is not None:
        if nsize is None or vsize != nsize:
            return False
    if vcolor is not None:
        if ncolor is None:
            return False
        if vcolor != ncolor and vcolor not in ncolor and ncolor not in vcolor:
            return False
    return True


# ---------------------------------------------------------------------------
# Name-drift merge — one physical item, many email phrasings.
#
# The SAME ordered item appears with a different name in each chain email
# ("Flow Y Nulu™ Bra" / "Flow Y Bra Nulu *Light Support, A–C Cups" /
# "Flow Y Nulu™ Bra LFRS 10"), splitting the v2 key. Within ONE order:
#   phase 1 — identical noise-stripped names merge unconditionally;
#   phase 2 — lines sharing (size, color) merge when the shorter name's tokens
#             are ≥60% contained in the longer's (guards two genuinely different
#             items that happen to share a size+color).
# ---------------------------------------------------------------------------

_NAME_SPLIT_RE = re.compile(r"[^0-9a-z\u0590-\u05ff]+")


def _name_tokens(name: Optional[str]) -> frozenset:
    toks = [t for t in _NAME_SPLIT_RE.split(strip_line_noise(name).lower()) if t]
    return frozenset(t for t in toks if not _SIZE_TOKEN_RE.match(t))


def _names_alike(a: Optional[str], b: Optional[str]) -> bool:
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(shorter & longer) / len(shorter) >= 0.6


def plan_name_merges(items: List[Tuple[str, Optional[str], Optional[str], Optional[str]]]
                     ) -> Dict[str, str]:
    """Plan same-order merges over (key, name, size, color) records.

    Returns {source_key: canonical_key}. Canonical = the longest (most complete)
    name of each merged cluster. Pure; caller applies the mapping (collapse keys
    in-memory, or absorb+demote rows in the DB)."""
    records = sorted(items, key=lambda r: len(strip_line_noise(r[1]) or ""), reverse=True)
    canon: List[Tuple[str, Optional[str], Optional[str], Optional[str]]] = []
    mapping: Dict[str, str] = {}
    for key, name, size, color in records:
        target = None
        sname = strip_line_noise(name).lower()
        for ckey, cname, csize, ccolor in canon:
            if sname and sname == strip_line_noise(cname).lower():
                target = ckey
                break
            same_sig = (
                (size or "").strip().lower() == (csize or "").strip().lower()
                and (color or "").strip().lower() == (ccolor or "").strip().lower()
                and (size or color)
            )
            if same_sig and _names_alike(name, cname):
                target = ckey
                break
        if target is None:
            canon.append((key, name, size, color))
        elif target != key:
            mapping[key] = target
    return mapping


def merge_order_name_drift(decisions: List[MessageDecision]) -> int:
    """Corpus-level name-drift merge: collapse same-order drifting keys. Returns
    #lines re-keyed. Runs AFTER enrichment_join (enriched rows already share keys)."""
    by_order: Dict[Tuple[Optional[str], Optional[str]], List[LineDecision]] = {}
    for md in decisions:
        for ld in md.admitted:
            if md.order_id and not ld.is_return:
                by_order.setdefault((normalize_name(md.merchant), md.order_id), []).append(ld)

    merged = 0
    for _grp, lines in by_order.items():
        seen: Dict[str, LineDecision] = {}
        uniq: List[Tuple[str, Optional[str], Optional[str], Optional[str]]] = []
        for ld in lines:
            if ld.content_key not in seen:
                seen[ld.content_key] = ld
                uniq.append((ld.content_key, ld.line.name, ld.line.size, ld.line.color))
        mapping = plan_name_merges(uniq)
        if not mapping:
            continue
        for ld in lines:
            target_key = mapping.get(ld.content_key)
            if target_key is None:
                continue
            target = seen[target_key]
            ld.content_key = target_key
            ld.line.name = target.line.name
            ld.line.size = ld.line.size or target.line.size
            ld.line.color = ld.line.color or target.line.color
            ld.needs_enrichment = ld.needs_enrichment and target.needs_enrichment
            merged += 1
    return merged


# Public alias: the DB-level incremental enrichment pass (extraction_service)
# reuses the exact same signature matcher as the in-memory corpus join above.
signatures_match = _matches
