"""Neutral cross-cutting infrastructure shared by every feature package (P3.3,
ARCHITECTURE_AUDIT R3).

Before this package existed, the Gemini client wrapper lived at
app.services.ai_provider and cost/usage accounting lived at
app.gmail_closet.usage -- each inside one feature package but imported at
module top-level by OTHER feature packages: app.services.stylist eagerly
imported app.gmail_closet.usage, and app.gmail_closet / app.photo_closet
eagerly imported app.services.ai_provider. That created a genuine
package-level cycle (services <-> gmail_closet <-> photo_closet) blocking
any future split into separately-deployable units.

app.platform is where cross-cutting infrastructure with no feature-specific
logic belongs: it may depend on app.core / app.db / app.models / app.utils
(the leaf/foundational layers), but NEVER on app.services, app.api,
app.gmail_closet, app.photo_closet, app.ranking, or app.monetization (the
business-logic / feature layers) -- locked by the
platform-depends-on-nothing-upward import-linter contract in .importlinter.

  ai_provider.py -- the Gemini client wrapper (structured generation, chat
                    tool-loop, embeddings, image generation).
  usage.py       -- provider-cost accounting (token/credit -> USD) shared by
                    the Gmail ingest pipeline and the AI Stylist.
"""
