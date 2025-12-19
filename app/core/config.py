"""Central configuration settings for the Tailor application."""

from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    OPENAI_API_KEY: str
    IMAGE_API_BASE_URL: str
    IMAGE_API_MODEL: str
    IMAGE_API_TIMEOUT: float

    GMAIL_IMAP_HOST: str
    GMAIL_IMAP_PORT: int
    GMAIL_MAX_YEARS: float
    GMAIL_IMAP_TIMEOUT: int

    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str

    SUPABASE_S3_ENDPOINT: str
    SUPABASE_S3_ACCESS_KEY: str
    SUPABASE_S3_SECRET_KEY: str
    SUPABASE_S3_BUCKET: str
    SUPABASE_PUBLIC_BASE_URL: str

    # Google OAuth configuration
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # JWT configuration
    JWT_SECRET_KEY: str = "change-this-secret-key-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra fields in .env without raising validation errors


settings = Settings()

