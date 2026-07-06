"""app.ranking — the shopping-feed Stage-1 ranker (F2, not yet built).

This package is intentionally created empty in F1c so the structural boundary can name
it NOW: `app.ranking` MUST NOT import `app.monetization` (enforced by import-linter, see
.importlinter). F2's ranker is therefore born on the correct side of the wall — it scores
products on taste_match / wardrobe_gap / price_fit / fatigue and can never read a payout,
commission, or affiliate-network field. Monetization happens only at click time, in
app/monetization, behind the /out/{click_id} redirect.
"""
