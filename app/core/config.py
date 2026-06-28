"""Central configuration settings for the Tailor application."""

from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # LLM Provider configuration
    LLM_PROVIDER: str = "gemini"
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    
    IMAGE_API_BASE_URL: str = ""
    IMAGE_API_MODEL: str = ""
    IMAGE_API_TIMEOUT: float = 30.0

    GMAIL_MAX_YEARS: float = 1.0
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

