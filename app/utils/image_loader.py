"""Image loader utility for loading local images as raw bytes."""

from dataclasses import dataclass
from pathlib import Path

import aiofiles


@dataclass
class ImageData:
    """Container for image data and format."""

    data: bytes
    format: str  # e.g. "jpeg", "png", "webp"


class ImageLoader:
    """Utility class for loading local image files as raw bytes."""

    @staticmethod
    async def load(image_path: str) -> ImageData:
        """
        Load a local image file and return its raw bytes + format
        suitable for OpenAI Vision 'input_image' content.

        Args:
            image_path: Path to the image file

        Returns:
            ImageData containing raw bytes and format string

        Raises:
            FileNotFoundError: If the image file does not exist
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Infer format from extension
        suffix = path.suffix.lower().lstrip(".")
        if suffix in ["jpg", "jpe"]:
            img_format = "jpeg"
        else:
            img_format = suffix or "jpeg"  # fallback

        async with aiofiles.open(path, "rb") as f:
            data = await f.read()

        return ImageData(data=data, format=img_format)

