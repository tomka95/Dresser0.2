import os
import uuid
from pathlib import Path
from typing import Optional

import boto3
from botocore.client import Config


class SupabaseStorageClient:
    """
    Simple S3-compatible client for Supabase Storage.
    """

    def __init__(self, bucket: str, public_base_url: Optional[str] = None):
        endpoint = os.environ["SUPABASE_S3_ENDPOINT"]
        access_key = os.environ["SUPABASE_S3_ACCESS_KEY"]
        secret_key = os.environ["SUPABASE_S3_SECRET_KEY"]

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
        bucket = os.environ["SUPABASE_S3_BUCKET"]
        public_base_url = os.getenv("SUPABASE_PUBLIC_BASE_URL")
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
