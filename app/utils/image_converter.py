"""Image converter utility for converting local images to base64."""

import base64
from pathlib import Path

import aiofiles


class ImageBase64Converter:
    """Utility class for converting local image files to base64-encoded bytes."""

    @staticmethod
    async def to_base64(image_path: str) -> bytes:
        """
        Read the file at `image_path` and return base64-encoded bytes.

        Args:
            image_path: Path to the image file (supports JPG, PNG, JPEG, WEBP, HEIC, etc.)

        Returns:
            Base64-encoded bytes of the image file

        Raises:
            FileNotFoundError: If the file does not exist
            IOError: If the file cannot be read
        """
        # 1. Validate path
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        if not path.is_file():
            raise IOError(f"Path is not a file: {image_path}")

        # 2. Open file async and read bytes
        try:
            async with aiofiles.open(path, "rb") as f:
                image_bytes = await f.read()
        except Exception as e:
            raise IOError(f"Failed to read image file {image_path}: {e}") from e

        # 3. Base64 encode
        base64_bytes = base64.b64encode(image_bytes)

        # 4. Return ONLY the raw b64 bytes
        return base64_bytes

