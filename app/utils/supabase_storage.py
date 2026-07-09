import uuid
from pathlib import Path
from typing import Optional

import boto3
from botocore.client import Config

from app.core.config import settings


def _require(value: Optional[str], name: str) -> str:
    """Fetch a required setting, raising KeyError(name) if unset.

    Matches the pre-P3.1 `os.environ[name]` failure mode exactly (same exception
    type + message) now that these values are sourced from `settings` instead of
    the environment directly.
    """
    if value is None:
        raise KeyError(name)
    return value


class SupabaseStorageClient:
    """
    Simple S3-compatible client for Supabase Storage.
    """

    def __init__(self, bucket: str, public_base_url: Optional[str] = None):
        endpoint = _require(settings.SUPABASE_S3_ENDPOINT, "SUPABASE_S3_ENDPOINT")
        access_key = _require(settings.SUPABASE_S3_ACCESS_KEY, "SUPABASE_S3_ACCESS_KEY")
        secret_key = _require(settings.SUPABASE_S3_SECRET_KEY, "SUPABASE_S3_SECRET_KEY")

        self.bucket = bucket
        self.public_base_url = public_base_url

        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4"),
        )

    @classmethod
    def from_env(cls) -> "SupabaseStorageClient":
        bucket = _require(settings.SUPABASE_S3_BUCKET, "SUPABASE_S3_BUCKET")
        public_base_url = settings.SUPABASE_PUBLIC_BASE_URL
        return cls(bucket=bucket, public_base_url=public_base_url)

    def upload_file(
        self,
        local_path: str,
        folder: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> str:
        suffix = Path(local_path).suffix or ".png"
        key = f"{uuid.uuid4().hex}{suffix}"
        if folder:
            key = f"{folder.rstrip('/')}/{key}"

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        self.s3.upload_file(local_path, self.bucket, key, ExtraArgs=extra_args)

        # If you configured a public base URL, construct a URL; otherwise return the key.
        if self.public_base_url:
            # Public URL style: /object/public/<bucket>/<key>
            return f"{self.public_base_url}/{self.bucket}/{key}"
        return key

    def delete_object(self, url_or_key: str) -> bool:
        """Delete one stored object by its public URL (or bare key). Best-effort.

        Photo-seam Phase 5 (raw-crop purge): once a verified card replaces a raw
        source crop, the crop blob is removed so a person-containing source cannot
        linger in public storage. Only OUR public-URL shape is parsed
        ({public_base_url}/{bucket}/{key}); anything else is refused (False).
        Returns True when a delete was issued, False otherwise. Never raises.
        """
        key = url_or_key or ""
        if self.public_base_url and key.startswith(f"{self.public_base_url}/{self.bucket}/"):
            key = key[len(f"{self.public_base_url}/{self.bucket}/"):]
        elif key.startswith("http://") or key.startswith("https://"):
            return False  # not our storage shape — never delete foreign URLs
        if not key or "/" not in key:
            return False  # bare/implausible key — refuse
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False  # best-effort: an orphan blob is acceptable, a crash is not

    def upload_bytes(
        self,
        image_bytes: bytes,
        folder: Optional[str] = None,
        content_type: Optional[str] = "image/png",
        suffix: str = ".png",
    ) -> str:
        """Upload image bytes directly to Supabase storage.
        
        Args:
            image_bytes: The image data as bytes
            folder: Optional folder path (e.g., "email_items/{user_id}")
            content_type: MIME type of the image (default: "image/png")
            suffix: File extension with dot (e.g., ".png", ".jpg")
            
        Returns:
            Public URL of the uploaded image
        """
        import io
        
        key = f"{uuid.uuid4().hex}{suffix}"
        if folder:
            key = f"{folder.rstrip('/')}/{key}"

        extra_args = {"ContentType": content_type}

        # Use upload_fileobj to upload from bytes
        file_obj = io.BytesIO(image_bytes)
        self.s3.upload_fileobj(file_obj, self.bucket, key, ExtraArgs=extra_args)

        # If you configured a public base URL, construct a URL; otherwise return the key.
        if self.public_base_url:
            # Public URL style: /object/public/<bucket>/<key>
            return f"{self.public_base_url}/{self.bucket}/{key}"
        return key