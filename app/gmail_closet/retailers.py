"""Curated allow-list of major global retail / e-commerce sender domains.

PURPOSE (phase 3b Tier 0/1 prep)
--------------------------------
A maintainable seed list of the biggest global online retailers and fashion
brands, keyed by their primary registrable sending domain. The 3b ingestion
pipeline will consume this to cheaply pre-classify a Gmail message's sender:

    Tier 0  -- sender domain IS a known retailer  -> high-prior receipt, fast-path
    Tier 1  -- sender domain is unknown           -> fall through to content heuristics

This module is DATA ONLY. It is intentionally NOT wired into the fetch/filter
path yet (no import of it from the Gmail client). 3b will import
``match_retailer`` / ``RETAILER_DOMAINS`` from here at the point where it decides
whether a message is purchase-like.

SOURCE
------
Seeded from publicly published "largest online retailers / e-commerce companies"
rankings (e.g. Digital Commerce 360 Top 1000, National Retail Federation Top
Retailers, Statista "leading online stores by revenue") plus the dominant global
fast-fashion / apparel brands. It is a representative top-of-market list, not
exhaustive -- it is meant to be extended over time.

HOW TO EXTEND
-------------
Add a ``"domain": "Display Name"`` entry to ``RETAILERS`` below, using the brand's
primary registrable domain (no scheme, no ``www.``, no mail subdomain). Marketing
mail commonly arrives from subdomains like ``e.``/``email.``/``news.``/``mail.``/
``order.`` -- ``match_retailer`` already strips those, so you only store the base
domain once (``nike.com``, not ``email.nike.com``).
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Optional

# Marketing/transactional mail subdomains to peel off before matching the base
# registrable domain (e.g. "e.lululemon.com" / "order.asos.com" -> "lululemon.com"
# / "asos.com"). Kept small and conservative on purpose.
_MAIL_SUBDOMAIN_PREFIXES = frozenset(
    {
        "e", "email", "emails", "mail", "news", "newsletter", "no-reply",
        "noreply", "order", "orders", "info", "hello", "shop", "store", "t",
        "send", "reply", "marketing", "go", "click", "links", "link", "m",
    }
)


# domain -> human-readable display name. Grouped by segment for easy maintenance.
RETAILERS: Dict[str, str] = {
    # --- Global marketplaces / general e-commerce ---------------------------
    "amazon.com": "Amazon",
    "ebay.com": "eBay",
    "etsy.com": "Etsy",
    "aliexpress.com": "AliExpress",
    "temu.com": "Temu",
    "walmart.com": "Walmart",
    "target.com": "Target",
    "wish.com": "Wish",
    "rakuten.com": "Rakuten",
    "mercadolibre.com": "Mercado Libre",
    # --- Fast fashion -------------------------------------------------------
    "shein.com": "SHEIN",
    "zara.com": "Zara",
    "hm.com": "H&M",
    "uniqlo.com": "Uniqlo",
    "mango.com": "Mango",
    "asos.com": "ASOS",
    "boohoo.com": "boohoo",
    "prettylittlething.com": "PrettyLittleThing",
    "missguided.com": "Missguided",
    "forever21.com": "Forever 21",
    "primark.com": "Primark",
    "bershka.com": "Bershka",
    "pullandbear.com": "Pull&Bear",
    "stradivarius.com": "Stradivarius",
    "massimodutti.com": "Massimo Dutti",
    "cos.com": "COS",
    "riverisland.com": "River Island",
    "newlook.com": "New Look",
    # --- Athletic / outdoor -------------------------------------------------
    "nike.com": "Nike",
    "adidas.com": "Adidas",
    "puma.com": "PUMA",
    "reebok.com": "Reebok",
    "newbalance.com": "New Balance",
    "underarmour.com": "Under Armour",
    "lululemon.com": "lululemon",
    "gymshark.com": "Gymshark",
    "vans.com": "Vans",
    "converse.com": "Converse",
    "asics.com": "ASICS",
    "thenorthface.com": "The North Face",
    "patagonia.com": "Patagonia",
    "columbia.com": "Columbia",
    "footlocker.com": "Foot Locker",
    "jdsports.com": "JD Sports",
    # --- Denim / casual / mid-market ----------------------------------------
    "levi.com": "Levi's",
    "gap.com": "Gap",
    "oldnavy.com": "Old Navy",
    "bananarepublic.com": "Banana Republic",
    "jcrew.com": "J.Crew",
    "madewell.com": "Madewell",
    "ae.com": "American Eagle",
    "aerie.com": "Aerie",
    "abercrombie.com": "Abercrombie & Fitch",
    "hollisterco.com": "Hollister",
    "urbanoutfitters.com": "Urban Outfitters",
    "anthropologie.com": "Anthropologie",
    "freepeople.com": "Free People",
    "next.co.uk": "Next",
    # --- DTC / contemporary -------------------------------------------------
    "everlane.com": "Everlane",
    "reformation.com": "Reformation",
    "revolve.com": "Revolve",
    "aritzia.com": "Aritzia",
    "skims.com": "SKIMS",
    "brandymelville.com": "Brandy Melville",
    "allsaints.com": "AllSaints",
    "tedbaker.com": "Ted Baker",
    "reiss.com": "Reiss",
    "zalando.com": "Zalando",
    "aboutyou.com": "ABOUT YOU",
    # --- Premium / luxury ---------------------------------------------------
    "net-a-porter.com": "NET-A-PORTER",
    "mrporter.com": "MR PORTER",
    "farfetch.com": "Farfetch",
    "ssense.com": "SSENSE",
    "mytheresa.com": "Mytheresa",
    "matchesfashion.com": "MATCHESFASHION",
    "yoox.com": "YOOX",
    "gucci.com": "Gucci",
    "burberry.com": "Burberry",
    "prada.com": "Prada",
    "louisvuitton.com": "Louis Vuitton",
    "balenciaga.com": "Balenciaga",
    "ralphlauren.com": "Ralph Lauren",
    "tommy.com": "Tommy Hilfiger",
    "calvinklein.com": "Calvin Klein",
    "lacoste.com": "Lacoste",
    # --- Department stores --------------------------------------------------
    "nordstrom.com": "Nordstrom",
    "macys.com": "Macy's",
    "bloomingdales.com": "Bloomingdale's",
    "saksfifthavenue.com": "Saks Fifth Avenue",
    "neimanmarcus.com": "Neiman Marcus",
    "selfridges.com": "Selfridges",
    "harrods.com": "Harrods",
    "johnlewis.com": "John Lewis",
    "marksandspencer.com": "Marks & Spencer",
    # --- Israel (local fashion retailers) -----------------------------------
    # Added in the Wave-0 image recovery. Terminal X self-hosts product imagery on
    # media.terminalx.com, matched here via the *.terminalx.com subdomain rule.
    # The others mainly improve Tier-0 sender classification AND cover any
    # self-hosted image subdomain; their product images otherwise sit on CDNs that
    # are already allow-listed (Shopify / Cloudfront / Adobe Scene7 / Wix).
    "terminalx.com": "Terminal X",
    "castro.co.il": "Castro",
    "factory54.co.il": "Factory 54",
    "fox.co.il": "Fox",
    "renuar.co.il": "Renuar",
    "adikastyle.com": "ADIKA",
    "delta.co.il": "Delta",
}


# Fast-membership set of the allow-listed base domains.
RETAILER_DOMAINS: FrozenSet[str] = frozenset(RETAILERS)


def normalize_sender_domain(sender: str) -> Optional[str]:
    """Reduce a raw From header or address to its base registrable domain.

    Handles ``"Brand <e.brand.com>"`` style headers, bare addresses, and peels off
    a single marketing/transactional mail subdomain (``e.``/``email.``/``news.``/
    ``order.`` ...). Returns a lowercased ``base.tld`` (or ``base.co.uk`` style
    second-level domain), or None if no domain can be extracted.

    NOTE: this is a deliberately small heuristic for sender allow-listing, not a
    full public-suffix-list parser. It is correct for the brands in RETAILERS.
    """
    if not sender:
        return None

    # Take whatever is after the last '@' (works for both "<a@b.com>" and "a@b.com").
    at = sender.rfind("@")
    candidate = sender[at + 1 :] if at != -1 else sender
    # Trim any trailing '>' or whitespace left by a "Name <addr>" header.
    candidate = candidate.strip().strip(">").strip().lower()
    if not candidate or "." not in candidate:
        return None

    labels = candidate.split(".")
    # Strip a single leading mail subdomain label if present and there's enough
    # left to still be a domain (>= 2 labels).
    if len(labels) > 2 and labels[0] in _MAIL_SUBDOMAIN_PREFIXES:
        labels = labels[1:]

    # Keep a 3-label domain when the last two labels look like a country second
    # level (e.g. co.uk, com.au); otherwise keep the final two labels.
    if len(labels) >= 3 and labels[-2] in {"co", "com", "org", "net", "gov", "ac"} and len(labels[-1]) == 2:
        base = ".".join(labels[-3:])
    else:
        base = ".".join(labels[-2:])
    return base or None


def match_retailer(sender: str) -> Optional[str]:
    """Return the display name if ``sender`` is a known retailer, else None.

    ``sender`` may be a full From header (``"Nike <email.nike.com>"``), a bare
    email address, or a domain. This is the entry point 3b's Tier-0 check calls.
    """
    domain = normalize_sender_domain(sender)
    if domain is None:
        return None
    return RETAILERS.get(domain)


def is_known_retailer(sender: str) -> bool:
    """True if ``sender`` resolves to an allow-listed retail domain."""
    return match_retailer(sender) is not None
