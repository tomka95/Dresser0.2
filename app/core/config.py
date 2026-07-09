"""Central configuration settings for the Tailor application."""

from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # LLM Provider configuration
    LLM_PROVIDER: str = "gemini"
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    # --- Gmail receipt extraction (phase 3c) -------------------------------
    # The extractor turns Tier-1-kept receipt emails into typed, confidence-scored
    # CLOTHING candidates via Gemini STRUCTURED OUTPUT. Flash-Lite is the default
    # (cheap, $0.10/$0.40 per 1M tok); we escalate to Flash ONLY on a parse failure
    # or when overall_confidence < the threshold below. Most emails never escalate.
    GEMINI_EXTRACT_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_EXTRACT_ESCALATION_MODEL: str = "gemini-2.5-flash"
    # Below this overall_confidence the cheap pass is re-run on the stronger model.
    GMAIL_EXTRACT_CONFIDENCE_THRESHOLD: float = 0.55
    # Concurrent LLM extractions per sync (kept modest to respect Gemini rate limits).
    GMAIL_EXTRACT_MAX_CONCURRENCY: int = 8
    # Hard cap on the email body chars sent to the model (token/cost guard).
    GMAIL_EXTRACT_MAX_BODY_CHARS: int = 12000
    # Layer C email-TYPE classifier: a cheap yes/no ("order confirmation vs marketing/
    # abandoned-cart") on subject+sender+snippet, run ONLY for the ambiguous residue
    # (known retailer + order-ish subject + price but no order number). Fail-open — if
    # disabled or the call errors, the email is KEPT so a genuine receipt is never dropped.
    GMAIL_TYPE_CLASSIFIER_ENABLED: bool = True
    GMAIL_TYPE_CLASSIFIER_MODEL: str = "gemini-2.5-flash-lite"
    
    # --- Photo -> closet garment detection (Wave 1) ------------------------
    # The schema-first detector behind /photo/ingest/detect. Returns per-garment
    # box_2d (+ optional mask) via Gemini structured output. Flash (not flash-lite)
    # for stronger spatial grounding; box/mask quality matters for the cutout.
    GEMINI_DETECT_MODEL: str = "gemini-2.5-flash"
    # How long a photo_detect_sessions row (detected regions awaiting the user's
    # selection, Wave 1.5) stays committable. Past this, commit returns 410 and the
    # row is swept on the user's next detect. Sessions hold hashes + boxes, never
    # the photo itself, so a generous default costs nothing sensitive.
    PHOTO_SESSION_TTL_HOURS: int = 24
    # Max photos whose Gemini detection runs CONCURRENTLY per /photo/ingest/detect call
    # (bounded worker pool). A 2+ photo upload detects in ~1 photo's time, not the sum,
    # without firing an unbounded number of model calls at once.
    PHOTO_DETECT_MAX_CONCURRENCY: int = 4

    IMAGE_API_BASE_URL: str = ""
    IMAGE_API_MODEL: str = ""
    IMAGE_API_TIMEOUT: float = 30.0

    # --- Cost model (editable per-unit rates for per-sync/per-user cost) -----
    # Dollar cost is computed from RECORDED units (real provider usage_metadata token
    # counts + issued Serper queries), never estimated — see app/gmail_closet/usage.py.
    # Rates are USD per 1,000,000 tokens so they read straight off the provider's
    # pricing page; bump them here when pricing changes (no code change needed).
    #   Gemini 2.5 Flash-Lite — the extraction base model AND the vision-verify model.
    GEMINI_FLASH_LITE_INPUT_USD_PER_1M: float = 0.10
    GEMINI_FLASH_LITE_OUTPUT_USD_PER_1M: float = 0.40
    #   Gemini 2.5 Flash — the extraction escalation model (stronger, pricier).
    GEMINI_FLASH_INPUT_USD_PER_1M: float = 0.30
    GEMINI_FLASH_OUTPUT_USD_PER_1M: float = 2.50
    #   Serper — one credit per issued shopping-search query (~$0.001 at 50k/$50).
    SERPER_USD_PER_CREDIT: float = 0.001

    # --- Image vision-verify (Wave 2b) -------------------------------------
    # A cheap Gemini vision check confirms a resolved image actually shows the
    # item's garment type + color before the image is trusted (and before its
    # product_image_cache row is flipped verified=true / served cross-user).
    # Reuses GEMINI_API_KEY. media_resolution=LOW (color + garment, not OCR).
    GMAIL_VERIFY_ENABLED: bool = True
    GMAIL_VERIFY_MODEL: str = "gemini-2.5-flash-lite"
    # Trust the image only when the model's overall match score >= this AND it says
    # the garment type matches. Conservative on garment; shade leniency is in the
    # prompt. ~$0.0002/image at LOW resolution.
    GMAIL_VERIFY_SCORE_THRESHOLD: float = 0.6
    # Per-run cost guard: at most this many verify calls per sync. Beyond it,
    # further images are left image_status='pending' for a later run to verify.
    GMAIL_VERIFY_MAX_PER_RUN: int = 200

    # --- Generation verify (Wave 2) -----------------------------------------
    # Model for the TWO-image reference-vs-generated verify pass
    # (image_verify.verify_generated_image). Stronger than the single-image
    # GMAIL_VERIFY_MODEL on purpose: the flash-lite tier canNOT judge logo
    # fidelity (count/placement) — it passed a duplicated-and-relocated swoosh
    # even at HIGH resolution, while gemini-2.5-flash catches it at medium. The
    # single-image color/garment pass stays on the cheaper flash-lite.
    GENERATION_VERIFY_MODEL: str = "gemini-2.5-flash"
    # Media resolution for the TWO-image reference-vs-generated verify pass
    # (image_verify.verify_generated_image). "low" | "medium" | "high".
    # Default medium: LOW is too coarse to judge logo/text presence reliably.
    # Unknown values fall back to medium (with a warning).
    GENERATION_VERIFY_MEDIA_RESOLUTION: str = "medium"

    # --- Long-tail shopping search (Wave 2c) -------------------------------
    # When the cache + email + og tiers all miss, query DataForSEO Google Shopping
    # (Merchant API, Standard async queue) by brand+name+color to find retailer
    # product pages, then resolve a FIRST-PARTY image from the retailer page and
    # vision-verify it before trusting. Opt-in (paid external API).
    GMAIL_SEARCH_ENABLED: bool = False
    # Which shopping-search provider Tier 5 uses. 'serper' (free tier, synchronous,
    # the default) or 'dataforseo' (async task queue). Both return the same
    # ShopCandidate(url, source_domain, title) shape.
    SEARCH_PROVIDER: str = "serper"
    SERPER_API_KEY: Optional[str] = None
    DATAFORSEO_LOGIN: Optional[str] = None
    DATAFORSEO_PASSWORD: Optional[str] = None
    # Cost cap: at most this many SHOPPING-SEARCH queries per sync.
    GMAIL_SEARCH_MAX_PER_RUN: int = 25
    # Candidate retailer links tried per item (ranked), before falling to pending.
    GMAIL_SEARCH_MAX_CANDIDATES: int = 3
    # Standard-queue poll: total seconds to wait for a task to be ready, and the
    # interval between task_get polls.
    GMAIL_SEARCH_POLL_TIMEOUT: float = 30.0
    GMAIL_SEARCH_POLL_INTERVAL: float = 2.0
    # Default localization for non-Hebrew items (Hebrew items auto-route to Israel).
    # LOCATION_CODE is DataForSEO's numeric geo; GL is Serper's 2-letter country.
    # LANGUAGE_CODE doubles as Serper's hl. (Hebrew items -> location 2376 / gl 'il' / he.)
    GMAIL_SEARCH_LOCATION_CODE: int = 2840   # United States (DataForSEO)
    GMAIL_SEARCH_GL: str = "us"              # Serper country code
    GMAIL_SEARCH_LANGUAGE_CODE: str = "en"   # hl / language_code

    # Anti-amplification: hard ceiling on outbound guarded fetches per sync. Covers
    # BOTH the retailer and the new "open" (non-allowlisted) profile, shared across
    # all items/candidates in the run.
    GMAIL_FETCH_MAX_PER_RUN: int = 100

    # --- Pluggable product-feed seam (Tier 4.5, Phase 4 stub) ---------------
    # A product-feed lookup (Sovrn / Awin / etc.) that maps brand+name+color -> a
    # first-party product image URL, sitting between og:image (Tier 4) and shopping
    # search (Tier 5). Ships disabled with a NullFeedProvider; a real provider plugs
    # in behind app/gmail_closet/feed_provider.get_feed_provider() with ZERO resolver
    # changes. Feed images route through the SAME guarded-fetch + vision-verify +
    # cache-seed path as every other untrusted-web tier (verify is mandatory).
    GMAIL_FEED_ENABLED: bool = False

    # --- Legacy outfit-photo pipeline (POST /outfit-image) ------------------
    # Models for the legacy multi-item outfit-photo flow (app.services.
    # clothing_pipeline -> app.platform.ai_provider's
    # _LegacyOutfitGenerationMixin). Superseded in the current web client by
    # the photo-ingest detect/commit flow + the Wave 2 image_generation
    # provider seam; kept working, not removed. Previously hardcoded inline
    # (ARCHITECTURE_AUDIT R8); centralized here so a model change needs no
    # code edit, like every other *_MODEL setting.
    LEGACY_OUTFIT_DETECT_MODEL: str = "gemini-2.5-flash-lite"
    LEGACY_OUTFIT_IMAGE_MODEL: str = "gemini-2.5-flash-image"

    # --- Image generation (Wave 2) ------------------------------------------
    # The generation seam (app/services/image_generation) turns a user photo
    # cutout into a clean product-card CANDIDATE image via an image-editing
    # model. Candidates are NEVER trusted directly — the vision-verify gate
    # decides whether one is shown. Ships disabled with a NullGenerationProvider;
    # nothing in the product flow calls the seam yet (the bake-off script does).
    GENERATION_ENABLED: bool = False
    # Which provider get_generation_provider() dispatches to (single-provider default;
    # the live ladders name their rungs explicitly):
    # 'flux2_pro' (BFL FLUX.2 [pro], the default rung-1) | 'flux_kontext' (BFL FLUX.1
    # Kontext [pro], kept selectable) | 'seedream' (fal.ai) | 'nano_banana' (Gemini
    # image gen, reuses GEMINI_API_KEY). Unknown/keyless -> Null.
    GENERATION_PROVIDER: str = "flux2_pro"
    BFL_API_KEY: Optional[str] = None
    FAL_API_KEY: Optional[str] = None
    # Gemini image model behind the nano_banana provider ("Nano Banana Pro").
    NANO_BANANA_MODEL: str = "gemini-3-pro-image-preview"
    # Total wall-clock budget per generation call (submit + poll + download).
    GENERATION_TIMEOUT_SECONDS: float = 90.0
    # Per-run cost guard: at most this many generation calls per run (bake-off).
    GENERATION_MAX_PER_RUN: int = 50
    # Max candidates generated CONCURRENTLY per run (bounded worker pool). Caps parallel
    # provider calls so a big batch doesn't hammer the provider APIs / hit rate limits: a
    # typical (<=6-garment) photo finishes in ~1 slow item (~15s), not the sum, while a
    # 50-item batch still runs 6-at-a-time. Shared GenerationBudget / VerifyBudget cap
    # total calls across the concurrent set.
    GENERATION_MAX_CONCURRENCY: int = 6
    # Editable per-IMAGE USD rates (same idea as the per-1M token rates above):
    # GenerationResult.cost_usd reads straight from these; bump on price change.
    # FLUX.2 [pro] (BFL, the rung-1 provider) is megapixel-priced: $0.03 for the first
    # output MP + $0.015/MP after, plus $0.015/MP for each reference (input) image.
    # Our flows always pass ONE ~1MP garment reference and produce a ~1MP card, so the
    # realistic per-image cost is $0.03 (output) + $0.015 (1 ref) = $0.045. Billed to
    # BFL_API_KEY (OFF the Gemini cap). nano_banana stays the on-cap rung-2 retry.
    FLUX2_PRO_USD_PER_IMAGE: float = 0.045
    FLUX_KONTEXT_USD_PER_IMAGE: float = 0.04
    SEEDREAM_USD_PER_IMAGE: float = 0.03
    NANO_BANANA_USD_PER_IMAGE: float = 0.134
    # Self-heal attempt ceiling (P2 cost cut): after this many FAILED generate→verify
    # attempts a target goes terminal (generation_status='failed') instead of perpetual
    # 'pending_retry', so a permanently-failing item stops being re-selected — and
    # re-billed gen + 2×verify — by every self-heal sweep. Genuinely-transient misses
    # (download error, budget, provider down) do NOT count toward this ceiling.
    GENERATION_MAX_ATTEMPTS: int = 3

    # --- Background image fill + self-heal (Phase 4) -----------------------
    # The slow image tiers (og:image / feed / search) and the cross-user self-heal
    # pass run in a background task AFTER the deck is shown, streaming images onto
    # cards as they resolve. This caps how many still-imageless candidates and how
    # many pending confirmed clothing_items one background run will touch (cost /
    # wall-clock guard; the per-run Verify/Fetch/Search budgets are the hard ceilings).
    GMAIL_IMAGE_FILL_MAX_CANDIDATES: int = 500
    GMAIL_SELF_HEAL_MAX_ITEMS: int = 500
    # Wave 2 generation self-heal: how many stale 'pending_retry' generation targets
    # (photo ingest_candidates + confirmed clothing_items whose card fell back to the raw
    # crop) one opportunistic sweep re-attempts. Modest by default — each target is a real
    # generation + verify call; the shared GENERATION_MAX_PER_RUN / GMAIL_VERIFY_MAX_PER_RUN
    # budgets are the hard ceilings, this just bounds how many rows a single sweep loads.
    GENERATION_SELF_HEAL_MAX_ITEMS: int = 30

    # How far back the Gmail receipt scan looks. Read via gmail_oauth_client.
    # default_since(); the deleted pipeline._calculate_since read an unset env var
    # (MAX_YEARS_TO_SCAN) and could raise on years <= 0.
    GMAIL_MAX_YEARS: float = 2.0
    GMAIL_IMAP_TIMEOUT: int = 30
    # DEV-ONLY Gmail scan cap (cost cut #5). When GMAIL_DEV_SCAN_CAP_ENABLED is True the
    # receipt scan is bounded to at most GMAIL_DEV_SCAN_MAX_MESSAGES message IDs and a
    # GMAIL_DEV_SCAN_MAX_DAYS window — so a dev iterating locally doesn't fetch + LLM-
    # extract a full 2-year mailbox. This is a PURE BOUND: no extraction/filter logic
    # changes. It is STRUCTURALLY off in prod — the flag defaults False, and every code
    # path that reads it falls back to the full scan (default_since / unbounded paging)
    # when it is unset. NEVER enable in a prod config.
    GMAIL_DEV_SCAN_CAP_ENABLED: bool = False
    GMAIL_DEV_SCAN_MAX_MESSAGES: int = 20
    GMAIL_DEV_SCAN_MAX_DAYS: int = 90

    # --- AI Stylist (Wave S0) ----------------------------------------------
    # Model seams for the Stylist. Branch A only defines them (nothing reads these
    # yet); Branch B/S1 wire them. Values are sensible Gemini defaults, overridable
    # via env.
    #   STYLIST_MODEL   : the reasoning model behind the stylist agent / distillation.
    #   EMBEDDING_MODEL : the item/text embedding model. gemini-embedding-001 (the
    #                     retired text-embedding-004 returns 404 NOT_FOUND on the
    #                     Gemini API's v1beta embedContent endpoint). Its native width
    #                     is 3072 but it supports Matryoshka (MRL) truncation, so we
    #                     pin output_dimensionality=EMBEDDING_DIM (768) at call time to
    #                     match the vector(768) column — no migration needed.
    #   EMBEDDING_DIM   : dimension of the vector column (item_embeddings.embedding).
    #                     Passed as output_dimensionality and MUST equal the vector(N)
    #                     declared in migration 0018 — changing it requires a migration.
    STYLIST_MODEL: str = "gemini-2.5-flash"
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIM: int = 768

    # --- Garment enrichment (Wave S0, Branch B) ----------------------------
    # The ASYNC pass that widens a confirmed item to the full Tier-1/2 schema
    # (subcategory, formality, warmth, seasons, occasions, pattern/material/fit,
    # hex, length, neckline, sleeve, heel). Runs on Flash-Lite AFTER confirm so the
    # ×3.4-10 output-token widening never touches the interactive deck path. Same
    # routine backs the eager post-confirm background task AND the nightly backfill;
    # both write provenance='inferred' and never overwrite 'user_edited'.
    ENRICHMENT_MODEL: str = "gemini-2.5-flash-lite"
    # Text embedding: RETRIEVAL_DOCUMENT indexes closet items (a search query would
    # embed with RETRIEVAL_QUERY). model/dim come from EMBEDDING_MODEL/EMBEDDING_DIM.
    EMBEDDING_TASK_TYPE_DOCUMENT: str = "RETRIEVAL_DOCUMENT"
    # item_embeddings.version for the CURRENT embedding recipe. Bump when the model or
    # canonical-text formula changes so old vectors can be re-embedded under a new row
    # (the UNIQUE is (item_id, model, version)).
    EMBEDDING_VERSION: int = 1
    # Nightly backfill cost/wall-clock guards. Max items one sweep loads per user, and
    # a hard ceiling on enrichment LLM calls per run (embedding is ~free, uncapped).
    ENRICHMENT_BACKFILL_MAX_ITEMS: int = 500
    ENRICHMENT_MAX_LLM_CALLS_PER_RUN: int = 500
    # Below this per-field confidence the enricher's value is written to attributes_json
    # (for provenance/debug) but NOT promoted to the flat query column — keeps the
    # composer's flat reads high-signal. Flat columns query; attributes_json audits.
    ENRICHMENT_FLAT_CONFIDENCE_MIN: float = 0.35

    # --- Interaction telemetry (Wave S0, Branch C) -------------------------
    # POST /events writes rows into style_events. user_id is ALWAYS the JWT
    # subject (never client-supplied). These guards bound abuse of the endpoint:
    #   EVENTS_MAX_BATCH        : max events accepted in one POST /events call.
    #   EVENTS_MAX_PROPERTIES_BYTES : cap on the JSON-serialized `properties` blob
    #                             per event (payload-size guard; over-limit -> 422).
    #   EVENTS_RATE_LIMIT_PER_MINUTE : per-user sliding-window ceiling on events
    #                             INGESTED via POST /events (batch counts as N).
    #                             In-process (per uvicorn worker); a shared limiter
    #                             (Redis) is the production upgrade. Server-derived
    #                             events (confirm/commit/PATCH) bypass this limit.
    EVENTS_MAX_BATCH: int = 50
    EVENTS_MAX_PROPERTIES_BYTES: int = 4096
    EVENTS_RATE_LIMIT_PER_MINUTE: int = 600

    # --- Monetization (Wave F1c) -------------------------------------------
    # The /out/{click_id} redirect wraps a product URL into an affiliate link at
    # click time. Account IDs are STUBS today (empty) — until Guy fills them the wrap
    # resolver returns the plain product URL. Secrets via env only. Only the
    # destination URL + opaque click_id ever leave us (no user id / email / closet).
    #   SOVRN_SITE_ID   : Sovrn/VigLink site id -> enables the Sovrn wrap (CUID=click_id).
    #   SKIMLINKS_PUBLISHER_ID : Skimlinks publisher id -> enables the Skimlinks wrap.
    #   MONETIZATION_DIRECT_DEEPLINK_ENABLED : allow per-program deep-links (SHEIN/AliExpress).
    #   CLICK_RATE_LIMIT_PER_MINUTE : per-user ceiling on POST /clicks + GET /out hits.
    SOVRN_SITE_ID: Optional[str] = None
    SKIMLINKS_PUBLISHER_ID: Optional[str] = None
    MONETIZATION_DIRECT_DEEPLINK_ENABLED: bool = True
    CLICK_RATE_LIMIT_PER_MINUTE: int = 120
    # Per-program direct affiliate ids (deep-link tier). Empty stubs today.
    SHEIN_AFFILIATE_ID: Optional[str] = None
    ALIEXPRESS_AFFILIATE_ID: Optional[str] = None

    # --- Onboarding seed (Wave S1) -----------------------------------------
    # POST /onboarding/seed writes the tap-only onboarding result into the S0
    # Style Profile tables (style_profiles.facts, style_preferences,
    # preference_signals). user_id is ALWAYS the JWT subject. These guards bound
    # a single seed payload (the whole flow commits once at the end):
    #   ONBOARDING_MAX_PREFERENCES : max style_preferences rows one seed upserts.
    #   ONBOARDING_MAX_SIGNALS     : max preference_signals rows one seed inserts
    #                                (taste deck is ~10 swipes; headroom for more).
    #   ONBOARDING_MAX_FACTS_BYTES : cap on the JSON-serialized facts blob merged
    #                                into style_profiles.facts (payload/PII guard).
    # The onboarding-derived confidence band clamps every seeded preference's
    # confidence into [MIN, MAX] regardless of client input (a self-reported taste
    # is a weak-to-moderate prior, never certainty).
    ONBOARDING_MAX_PREFERENCES: int = 40
    ONBOARDING_MAX_SIGNALS: int = 60
    ONBOARDING_MAX_FACTS_BYTES: int = 8192
    ONBOARDING_CONFIDENCE_MIN: float = 0.5
    ONBOARDING_CONFIDENCE_MAX: float = 0.6

    # --- AI Stylist Chat (Wave S2) ------------------------------------------
    # Model routing (locked decision 3): Flash (STYLIST_MODEL above) is the
    # default compose/chat model; a Flash-Lite pre-parse classifies intent /
    # explicit deep-reasoning requests per turn; Pro runs ONLY when the user
    # explicitly asks for deep reasoning (mirrors the extract Lite->Flash
    # escalation pattern — cheap first, stronger only when needed).
    STYLIST_LITE_MODEL: str = "gemini-2.5-flash-lite"
    STYLIST_ESCALATION_MODEL: str = "gemini-2.5-pro"
    #   Gemini 2.5 Pro rates (USD per 1M tokens; <=200k-token prompts tier).
    GEMINI_PRO_INPUT_USD_PER_1M: float = 1.25
    GEMINI_PRO_OUTPUT_USD_PER_1M: float = 10.0

    # Input guards (payload-size / abuse controls; oversized -> 413/422).
    CHAT_MAX_MESSAGE_CHARS: int = 4000
    CHAT_MAX_ATTACHMENTS: int = 3
    CHAT_MAX_BODY_BYTES: int = 8_000_000  # whole-request ceiling (base64 images)

    # Context assembly: windowed transcript + retrieved closet SUBSET (never a
    # full closet dump) keeps per-turn input tokens bounded.
    CHAT_HISTORY_WINDOW: int = 12          # prior messages replayed per turn
    CHAT_MAX_TOOL_ROUNDS: int = 6          # agent-loop hard stop (fail closed)
    CHAT_RETRIEVAL_LIMIT: int = 24         # max closet items per search_closet call
    CHAT_TURN_TIMEOUT_SECONDS: float = 120.0

    # Shared (cross-worker, Postgres-backed) abuse controls. Redis is not part of
    # this stack; the DB is the one shared, durable store every worker already
    # has, so the limiter/quota state lives there (chat_rate_windows/chat_usage).
    CHAT_RATE_LIMIT_PER_MINUTE: int = 10   # fixed 60s window per user
    CHAT_MAX_CONCURRENT_STREAMS: int = 2   # per-user in-flight SSE turns
    CHAT_DAILY_TURN_QUOTA: int = 60        # free-tier: turns per user per UTC day
    CHAT_DAILY_COST_QUOTA_USD: float = 0.50  # free-tier: $ per user per UTC day

    # Retention TTL for conversations (rolling: each message pushes it forward).
    CHAT_RETENTION_DAYS: int = 90

    # --- Preference learning / distillation (Wave S3) ----------------------
    # Two passes over the S0/S1 preference substrate:
    #   1. POST-SESSION chat distill (distill_background): after each chat turn a
    #      Flash-Lite pass mines like/dislike/constraint/context signals from the
    #      recent transcript window and appends preference_signals(source=
    #      'chat_inferred') + a short episodic session summary. Cheap (~$0.001/
    #      session), off the response path, never raises.
    #   2. NIGHTLY re-distill (run_redistill / scripts.dev_redistill): decays every
    #      style_preferences.confidence by its staleness, recomputes preferences
    #      from the aggregated signals (explicit ALWAYS outranks inferred), then
    #      regenerates style_profiles.narrative_blob and bumps version/distilled_at.
    DISTILL_ENABLED: bool = True
    # Distillation runs on the cheap Lite tier — mining is a small structured-JSON
    # task, not reasoning. Own seam so it can move independently of the chat model.
    DISTILL_MODEL: str = "gemini-2.5-flash-lite"
    # Chat-distill: trailing transcript messages the miner reads, and the hard cap
    # on preference_signals one session-distill may append (bounds a pathological
    # long turn's cost + write volume).
    DISTILL_MESSAGE_WINDOW: int = 12
    DISTILL_MAX_SIGNALS_PER_SESSION: int = 12
    # Session-end mine depth (cost cut #4). Because distillation now fires ONCE per session
    # (not per turn), the single end-of-session pass reads a DEEPER trailing window than the
    # per-turn default so a whole typical session is mined in one call — nothing an earlier
    # per-turn pass would have seen (before it scrolled out of the 12-msg window) is dropped.
    # Still one cheap Lite call per session (~$0.001).
    DISTILL_SESSION_MESSAGE_WINDOW: int = 40
    # Confidence decay (nightly): a preference loses half its confidence every
    # HALFLIFE_DAYS it goes un-reinforced (Δt measured from last_seen_at). λ =
    # ln(2)/HALFLIFE_DAYS; confidence *= exp(-λ·Δt_days). An INFERRED preference
    # that decays below ACTIVE_MIN_CONFIDENCE is flipped active=false (dropped from
    # the profile); explicit/onboarding rows are never auto-deactivated (a user who
    # stated a taste keeps it until they change it).
    DISTILL_CONFIDENCE_HALFLIFE_DAYS: float = 30.0
    DISTILL_ACTIVE_MIN_CONFIDENCE: float = 0.15
    # Recompute: signals older than LOOKBACK_DAYS are treated as fully decayed and
    # ignored. Confidence from fresh signals saturates via 1-exp(-GAIN·evidence),
    # and an INFERRED preference can never exceed MAX_INFERRED_CONFIDENCE (an
    # inference is never certainty — only an explicit statement can score higher).
    DISTILL_SIGNAL_LOOKBACK_DAYS: int = 180
    DISTILL_CONFIDENCE_GAIN: float = 0.7
    DISTILL_MAX_INFERRED_CONFIDENCE: float = 0.85
    # Nightly narrative regeneration is the only LLM call per user in re-distill;
    # this caps total narrative calls across an --all sweep (cost guard, mirrors
    # ENRICHMENT_MAX_LLM_CALLS_PER_RUN). Decay + recompute are pure-Python + free.
    DISTILL_MAX_NARRATIVE_CALLS_PER_RUN: int = 1000
    # Chat distillation fires ONCE PER SESSION, not per turn (cost cut P?/PRD spec —
    # ~$0.001/session, not ~$0.001 × every turn). A conversation is "ended" once it has
    # gone IDLE for this many minutes with no new message; a dirty-session sweep (run off
    # the chat response path at the next turn's tail, plus the nightly backstop) then
    # distills each ended-but-not-yet-distilled conversation exactly once. Bounds how many
    # such sessions one sweep mines (cost guard; each is one Lite miner call).
    DISTILL_SESSION_IDLE_MINUTES: int = 30
    DISTILL_SWEEP_MAX_SESSIONS: int = 20

    # --- Durable job queue (P3.8, ARCHITECTURE_AUDIT R1, Wave 1) ------------
    # A Postgres-native durable queue (jobs table, claimed via FOR UPDATE SKIP
    # LOCKED, reclaimed after a crash by a stale-lock sweep) replaces the
    # process-bound BackgroundTasks/daemon-thread dispatch for background work.
    # Same "the DB is the one shared, durable store" posture as the chat rate
    # limiter above -- no broker, no Redis. The worker runs as a SECOND long-lived
    # process: `python -m app.worker`. See app/platform/jobs/ + app/worker.py.
    #
    # PER-TYPE cutover flags, default OFF -> byte-identical to today (routes keep
    # calling background_tasks.add_task). Flip ON -> the route enqueues a jobs row
    # (transactionally, with the IngestRun) and the worker does the work. The flag
    # is read ONCE at request/dispatch time, so a sync already running in a
    # threadpool thread when the flag flips finishes there untouched -- no drain,
    # no in-flight breakage. Only the two already-idempotent jobs are wired in
    # Wave 1; enrichment + distill are Wave 2.
    JOBS_GMAIL_INGEST_ENABLED: bool = False
    JOBS_PHOTO_GENERATION_ENABLED: bool = False

    # Worker loop tuning (only consulted by app/worker.py; inert with flags OFF).
    JOBS_POLL_INTERVAL_SECONDS: float = 2.0    # idle sleep between empty claims
    # Stale-lock threshold: a 'running' job whose locked_at is older than this is
    # assumed crashed and reclaimed. MUST exceed the worst-case healthy runtime of
    # the longest job (gmail_ingest runs minutes) or a slow-but-healthy sync gets
    # falsely reclaimed. Generous by default; a per-job heartbeat (Wave 2) is the
    # way to tighten crash-detection latency without this tradeoff.
    JOBS_STALE_SECONDS: float = 1800.0         # 30 min
    JOBS_MAX_ATTEMPTS: int = 3                 # default retry ceiling per job
    JOBS_RETRY_BASE_SECONDS: float = 2.0       # exp backoff base
    JOBS_RETRY_MAX_SECONDS: float = 60.0       # exp backoff cap
    # Worker identity stamped into jobs.locked_by (observability only). Defaults to
    # the hostname when unset (resolved in app/worker.py).
    JOBS_WORKER_ID: Optional[str] = None

    # --- Shopping feed: Stage-1 ranker + wardrobe-gap job (Wave F2) ---------
    # The feed scores each product with an INTERPRETABLE linear model (no learned
    # weights). All coefficients live HERE, never inlined in the ranker, so a weight
    # change is one edit and the golden test (tests/test_ranker_golden.py) makes the
    # effect on scoring visible. Feed serve + gap job are both $0 API (pgvector + CPU).
    #
    #   score = W_TASTE·taste_match + W_GAP·wardrobe_gap + W_PRICE·price_fit
    #           + W_QUALITY·quality_recency − W_FATIGUE·fatigue
    RANKING_W_TASTE: float = 0.40      # cosine(product, taste-blend), the primary signal
    RANKING_W_GAP: float = 0.25        # marginal outfits unlocked vs the current closet
    RANKING_W_PRICE: float = 0.15      # gaussian fit to the user's budget band
    RANKING_W_QUALITY: float = 0.12    # freshness / in-stock / verified-image quality
    RANKING_W_FATIGUE: float = 0.18    # subtractive: decays a product seen too often

    # taste-blend = α·liked-centroid ⊕ β·closet-centroid ⊕ γ·archetype-centroid.
    # α grows and γ shrinks with behavioural evidence (schedule g = exp(−evidence/SCALE)):
    # a cold-start user is all-archetype; a user with likes + a closet is taste-driven.
    RANKING_BLEND_ALPHA: float = 0.60          # warm-state weight on liked-items centroid
    RANKING_BLEND_BETA: float = 0.40           # weight on the closet centroid (when present)
    RANKING_BLEND_GAMMA: float = 0.15          # warm-state weight on archetype centroid
    RANKING_BLEND_EVIDENCE_SCALE: float = 8.0  # behavioural signals for ~63% warm-up

    # wardrobe_gap term = log(1+unlock_count) normalised per user, + a bonus when the
    # product fills an L1 occasion the closet covers ZERO of (an empty-context unlock).
    RANKING_GAP_OCCASION_BONUS: float = 0.25

    # price_fit = gaussian(price; centre=budget mid, σ=RANKING_PRICE_SIGMA_FRAC·mid).
    # A missing price or an unknown band scores neutral (RANKING_PRICE_NEUTRAL).
    RANKING_PRICE_SIGMA_FRAC: float = 0.5
    RANKING_PRICE_NEUTRAL: float = 0.5

    # fatigue = 1 − exp(−DECAY·impressions) from style_events (per user,product).
    RANKING_FATIGUE_DECAY: float = 0.35

    # Re-rank layer. MMR trades relevance vs diversity over product embeddings
    # (λ=1 pure relevance, λ=0 pure diversity). Category calibration nudges the feed's
    # category mix toward the user's closet+occasions mix. An exploration slice
    # (ε of positions) injects adjacent-archetype/category items, each FLAGGED so its
    # impression is learnable-apart in style_events.
    RANKING_MMR_LAMBDA: float = 0.70
    RANKING_EXPLORATION_EPSILON: float = 0.18   # 15–20% of feed positions are exploration
    RANKING_CATEGORY_CALIBRATION: float = 0.5   # 0 = ignore closet mix, 1 = match it hard

    # Feed composition. ~70% product cards, ~30% outfit cards (owned items + 1 buyable).
    RANKING_OUTFIT_CARD_RATIO: float = 0.30
    RANKING_FEED_PAGE_SIZE: int = 24
    # A user needs at least this many closet items before outfit cards are built (below
    # it there is nothing to compose against → cold-start "starter looks", product-only).
    RANKING_OUTFIT_MIN_CLOSET: int = 4

    # wardrobe-gap job combinatorics caps (bound the nightly CPU cost):
    #   CANDIDATE_K : top-K products by taste_match scored per user (the candidate pool).
    #   SLOT_TOP_M  : per slot, keep only the top-M embedding-diverse owned representatives
    #                 before the marginal-unlock grid — caps assemble_from_pool's fan-out.
    RANKING_GAP_CANDIDATE_K: int = 400
    RANKING_GAP_SLOT_TOP_M: int = 15

    # Defense-in-depth (locked decision 1): run agent tool DB access on an
    # RLS-ENFORCED connection (SET LOCAL role authenticated + request.jwt.claims)
    # so Postgres RLS backstops the app-level WHERE user_id. Fail-loud: if the
    # role switch fails on Postgres the turn 503s rather than silently running
    # unscoped. Only disable for local Postgres without Supabase roles.
    CHAT_RLS_ENFORCED: bool = True

    # --- Weather context (Open-Meteo; NO API key) --------------------------
    # Real weather for the stylist, compose_outfit warmth, and the Home tile.
    # Open-Meteo is free and keyless, so the feature ships ENABLED by default.
    # The service is a read-through cache over `weather_cache` (service-role
    # read/write — the table is deny-all under RLS); location comes from the
    # already-captured style_profiles.facts.location (lat/lon coarsened ~1km).
    #   WEATHER_API_BASE_URL : override only to self-host or point tests at a stub.
    #   WEATHER_CACHE_TTL_SECONDS : read-through freshness window (current conditions
    #                     refresh at most this often per ~1km cell).
    WEATHER_ENABLED: bool = True
    WEATHER_PROVIDER: str = "open_meteo"
    WEATHER_API_BASE_URL: str = "https://api.open-meteo.com/v1/forecast"
    WEATHER_TIMEOUT_SECONDS: float = 8.0
    WEATHER_CACHE_TTL_SECONDS: int = 3600  # 1 hour

    # --- CORS ---------------------------------------------------------------
    # Comma-separated list of allowed browser origins, parsed by `cors_origins`.
    # The localhost defaults are DEV-ONLY; every shipped environment overrides
    # CORS_ALLOWED_ORIGINS with the real web origin(s). Origins are matched
    # exactly (no wildcard is used together with allow_credentials).
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Database configuration.
    # No localhost/postgres defaults on purpose: a missing value must surface as a
    # clear configuration error rather than silently pointing the app at a local DB.
    # The connection URL is assembled in app/db.py, which is the single place that
    # decides between the configured remote DB and an explicit local-dev opt-in.
    # Every env var db.py consults lives here (P3.1) -- db.py never reads os.environ
    # for configuration, so there is exactly one source of truth per var.
    DATABASE_URL: Optional[str] = None
    DATABASE_URI: Optional[str] = None  # legacy alias, checked after DATABASE_URL
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = None
    DB_HOST: Optional[str] = None
    DB_PORT: Optional[int] = None
    DB_NAME: Optional[str] = None

    # Explicit local-dev opt-in (see app/db.py._local_mode). Kept as raw strings
    # (not bool) so the truthy-string parsing in db.py is byte-for-byte identical
    # to the pre-P3.1 os.getenv() behavior -- pydantic's own bool coercion accepts
    # a slightly different string set and would be a silent behavior change here.
    LOCAL_DB: Optional[str] = None
    USE_SQLITE: Optional[str] = None
    # Dev/test-only escape hatch letting the test suite point at a remote DB
    # (app/db.py._guard_test_engine normally refuses this). Same raw-string-truthy
    # reasoning as above.
    ALLOW_REMOTE_TEST_DB: Optional[str] = None

    SUPABASE_S3_ENDPOINT: Optional[str] = None
    SUPABASE_S3_ACCESS_KEY: Optional[str] = None
    SUPABASE_S3_SECRET_KEY: Optional[str] = None
    SUPABASE_S3_BUCKET: Optional[str] = None
    SUPABASE_PUBLIC_BASE_URL: Optional[str] = None

    # --- Gmail ingest OAuth (dedicated "Tailor Gmail Ingest" Google client) -----
    # This is the SEPARATE Google OAuth client used ONLY to obtain a
    # gmail.readonly refresh token for receipt ingestion. It is NOT the login
    # client: "Login with Google" is owned entirely by Supabase Auth (its client
    # id/secret live in the Supabase dashboard and never touch this backend).
    #
    # The legacy single-client GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI were retired
    # in the Gmail-connect cutover; do not reintroduce them. The backend always
    # uses GMAIL_OAUTH_REDIRECT_URI from env and never honors a caller-supplied
    # redirect_uri (which was the open-redirect foot-gun in the old flow).
    GMAIL_OAUTH_CLIENT_ID: Optional[str] = None
    GMAIL_OAUTH_CLIENT_SECRET: Optional[str] = None
    GMAIL_OAUTH_REDIRECT_URI: str = "http://localhost:3000/gmail/oauth/callback"
    # The only scope this client ever requests. gmail.readonly is read-only mail
    # access; no identity scopes (login already established identity via Supabase).
    GMAIL_OAUTH_SCOPE: str = "https://www.googleapis.com/auth/gmail.readonly"

    # Secret used to sign the short-lived OAuth `state` (CSRF) token that binds the
    # consent round-trip to the initiating user's session. Independent of the
    # legacy login JWT secret on purpose (different purpose, different rotation).
    GMAIL_OAUTH_STATE_SECRET: Optional[str] = None
    GMAIL_OAUTH_STATE_TTL_SECONDS: int = 600  # consent must complete within 10 min

    # Base64-encoded 32-byte key (AES-256) for at-rest encryption of the Gmail
    # access/refresh tokens stored in google_accounts. Held in env only, NEVER in
    # the database, so a DB compromise alone yields only ciphertext. Decryption
    # happens exclusively inside the token-refresh service.
    GMAIL_TOKEN_ENC_KEY: Optional[str] = None

    # --- Calendar-connect OAuth (dedicated "Tailor Calendar" Google client) -----
    # SEPARATE Google OAuth client used ONLY to obtain a calendar.events.readonly
    # refresh token. NOT the login client (Supabase owns login) and NOT the Gmail
    # ingest client — a distinct surface gets a distinct client, mirroring the
    # Gmail-connect split. The backend always uses CALENDAR_OAUTH_REDIRECT_URI from
    # env and never honors a caller-supplied redirect_uri (open-redirect defense).
    CALENDAR_OAUTH_CLIENT_ID: Optional[str] = None
    CALENDAR_OAUTH_CLIENT_SECRET: Optional[str] = None
    CALENDAR_OAUTH_REDIRECT_URI: str = "http://localhost:3000/calendar/oauth/callback"
    # The ONLY scope this client ever requests. Read-only event access — enough to
    # read "what's on your day" + derive dress-code hints, nothing more (no write,
    # no calendar-list/settings, no freebusy-only blind spot). Server-fixed.
    CALENDAR_OAUTH_SCOPE: str = "https://www.googleapis.com/auth/calendar.events.readonly"

    # Secret signing the short-lived OAuth `state` (CSRF) token for the calendar
    # flow. Independent of the Gmail state secret. The state's `purpose` claim is
    # 'calendar_oauth_connect' so a Gmail-issued state can NEVER be replayed into
    # the calendar callback (purpose check rejects it even if secrets matched).
    CALENDAR_OAUTH_STATE_SECRET: Optional[str] = None
    CALENDAR_OAUTH_STATE_TTL_SECONDS: int = 600  # consent must complete within 10 min

    # Calendar token at-rest encryption reuses app/core/token_crypto (AES-256-GCM)
    # and the SAME GMAIL_TOKEN_ENC_KEY — one env-only key, never in the DB. The
    # per-field AAD ("access_token"/"refresh_token") is unchanged.
    #
    # Per-turn stylist context reads calendar events LIVE (never persisted). This
    # toggles the whole feature; OFF => assemble_calendar/endpoint no-op.
    CALENDAR_ENABLED: bool = True
    # How many of today's upcoming events the stylist context + Home tile read.
    CALENDAR_MAX_EVENTS: int = 6
    # Rolling window (in days, incl. today) the STYLIST context reads so it can
    # answer "what should I wear tomorrow / on Friday?" — every event is date +
    # weekday tagged in the prompt so the model never guesses which day it's on.
    # Still a LIVE per-request fetch; no titles persisted. The Home tile stays
    # today-only (GET /calendar/today is unaffected by this).
    CALENDAR_CONTEXT_DAYS: int = 7
    # Short-lived, per-user, IN-PROCESS cache for GET /calendar/today so rapid
    # Home re-mounts don't re-hit Google every time. EPHEMERAL memory only — no
    # DB storage, no event titles persisted (the no-titles-in-DB rule stands).
    CALENDAR_TODAY_CACHE_TTL_SECONDS: int = 90

    # NOTE: the legacy custom-JWT settings (JWT_SECRET_KEY / JWT_ALGORITHM /
    # JWT_ACCESS_TOKEN_EXPIRE_MINUTES) were REMOVED in the auth-hardening pass.
    # There is no shared HS256 secret anymore: the backend accepts ONLY asymmetric
    # Supabase access tokens (see app/supabase_auth.py, app/dependencies.py), so
    # there is no forgeable default key to leave lying around.

    # --- Supabase Auth (identity) ------------------------------------------
    # Supabase Auth (auth.users) is being introduced as the identity source.
    # NONE of these are secrets: the project ref and the JWKS endpoint are public
    # (they appear in every client URL), and verification uses the project's
    # PUBLIC asymmetric signing keys fetched from JWKS. The legacy shared JWT
    # secret is deliberately NOT used for Supabase verification.
    #
    # Only SUPABASE_PROJECT_REF (or an explicit URL/JWKS override) is required to
    # turn on Supabase-token acceptance; the issuer/JWKS URL are derived from it.
    SUPABASE_PROJECT_REF: Optional[str] = None
    SUPABASE_URL: Optional[str] = None            # e.g. https://<ref>.supabase.co
    SUPABASE_JWKS_URL: Optional[str] = None        # explicit override; else derived
    SUPABASE_JWT_ISSUER: Optional[str] = None      # explicit override; else derived
    SUPABASE_JWT_AUDIENCE: str = "authenticated"   # Supabase access-token aud claim
    SUPABASE_JWKS_CACHE_TTL_SECONDS: int = 3600

    @property
    def cors_origins(self) -> list:
        """Allowed CORS origins as a list (parsed from CORS_ALLOWED_ORIGINS)."""
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def supabase_base_url(self) -> Optional[str]:
        """Base project URL, from SUPABASE_URL or derived from the project ref."""
        if self.SUPABASE_URL:
            return self.SUPABASE_URL.rstrip("/")
        if self.SUPABASE_PROJECT_REF:
            return f"https://{self.SUPABASE_PROJECT_REF}.supabase.co"
        return None

    @property
    def supabase_jwks_url(self) -> Optional[str]:
        """JWKS endpoint for the project's public signing keys."""
        if self.SUPABASE_JWKS_URL:
            return self.SUPABASE_JWKS_URL
        base = self.supabase_base_url
        return f"{base}/auth/v1/.well-known/jwks.json" if base else None

    @property
    def supabase_jwt_issuer(self) -> Optional[str]:
        """Expected `iss` claim on Supabase-issued tokens."""
        if self.SUPABASE_JWT_ISSUER:
            return self.SUPABASE_JWT_ISSUER
        base = self.supabase_base_url
        return f"{base}/auth/v1" if base else None

    @property
    def supabase_auth_enabled(self) -> bool:
        """True when enough config is present to verify Supabase tokens."""
        return bool(self.supabase_jwks_url and self.supabase_jwt_issuer)

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra fields in .env without raising validation errors


settings = Settings()

