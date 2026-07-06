"""app.monetization — click-time affiliate redirect, quarantined from ranking.

Everything that turns a product click into money lives here and NOWHERE else:
  * routes.py  — POST /clicks (mint an opaque click_id) + GET /out/{click_id} (302).
  * wrap.py    — the wrap resolver: deep-link -> Sovrn -> Skimlinks -> plain fallback.
  * service.py — mint_click / resolve_destination (id-lookup only) + conversion writes.
  * config.py  — env-backed account-id stubs (empty today -> plain redirect).

STRUCTURAL BOUNDARY (import-linter, .importlinter): app.ranking and the outfit
composer/compat MUST NOT import this package, and this package MUST NOT import them.
Ranking scores garments on taste/gap/price/fatigue; it must be physically unable to see a
payout. The only things that ever leave us on the wire are the destination URL and the
opaque click_id — never a user id, email, or closet datum.
"""
