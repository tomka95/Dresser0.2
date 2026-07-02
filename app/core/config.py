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

    # --- Image generation (Wave 2) ------------------------------------------
    # The generation seam (app/services/image_generation) turns a user photo
    # cutout into a clean product-card CANDIDATE image via an image-editing
    # model. Candidates are NEVER trusted directly — the vision-verify gate
    # decides whether one is shown. Ships disabled with a NullGenerationProvider;
    # nothing in the product flow calls the seam yet (the bake-off script does).
    GENERATION_ENABLED: bool = False
    # Which provider get_generation_provider() dispatches to:
    # 'flux_kontext' (BFL, the default) | 'seedream' (fal.ai) | 'nano_banana'
    # (Gemini image gen, reuses GEMINI_API_KEY). Unknown/keyless -> Null.
    GENERATION_PROVIDER: str = "flux_kontext"
    BFL_API_KEY: Optional[str] = None
    FAL_API_KEY: Optional[str] = None
    # Gemini image model behind the nano_banana provider ("Nano Banana Pro").
    NANO_BANANA_MODEL: str = "gemini-3-pro-image-preview"
    # Total wall-clock budget per generation call (submit + poll + download).
    GENERATION_TIMEOUT_SECONDS: float = 90.0
    # Per-run cost guard: at most this many generation calls per run (bake-off).
    GENERATION_MAX_PER_RUN: int = 50
    # Editable per-IMAGE USD rates (same idea as the per-1M token rates above):
    # GenerationResult.cost_usd reads straight from these; bump on price change.
    FLUX_KONTEXT_USD_PER_IMAGE: float = 0.04
    SEEDREAM_USD_PER_IMAGE: float = 0.03
    NANO_BANANA_USD_PER_IMAGE: float = 0.134

    # --- Background image fill + self-heal (Phase 4) -----------------------
    # The slow image tiers (og:image / feed / search) and the cross-user self-heal
    # pass run in a background task AFTER the deck is shown, streaming images onto
    # cards as they resolve. This caps how many still-imageless candidates and how
    # many pending confirmed clothing_items one background run will touch (cost /
    # wall-clock guard; the per-run Verify/Fetch/Search budgets are the hard ceilings).
    GMAIL_IMAGE_FILL_MAX_CANDIDATES: int = 500
    GMAIL_SELF_HEAL_MAX_ITEMS: int = 500

    # How far back the Gmail receipt scan looks. Read via gmail_oauth_client.
    # default_since(); the deleted pipeline._calculate_since read an unset env var
    # (MAX_YEARS_TO_SCAN) and could raise on years <= 0.
    GMAIL_MAX_YEARS: float = 2.0
    GMAIL_IMAP_TIMEOUT: int = 30

    # Database configuration.
    # No localhost/postgres defaults on purpose: a missing value must surface as a
    # clear configuration error rather than silently pointing the app at a local DB.
    # The connection URL is assembled in app/db.py, which is the single place that
    # decides between the configured remote DB and an explicit local-dev opt-in.
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = None
    DB_HOST: Optional[str] = None
    DB_PORT: Optional[int] = None
    DB_NAME: Optional[str] = None

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

    # JWT configuration (legacy custom-JWT path, signed with JWT_SECRET_KEY).
    # Kept live during the Supabase Auth transition (dual-accept). Rotate before
    # production.
    JWT_SECRET_KEY: str = "change-this-secret-key-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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

