from typing import Optional

from app.services.email_image_extraction import EmailImages, choose_best_image_for_email
from app.services.openai_image_service import generate_white_background_item_from_bytes


def enrich_item_with_generated_photo_from_email(
    *,
    email_html: str,
    email_inline_images: list[bytes],
    item_name: str,
) -> Optional[str]:
    """
    Returns a URL/path to the generated white-background image for this item,
    or None if we couldn't get any image.
    """
    email_images = EmailImages(
        html_body=email_html,
        inline_images=email_inline_images,
    )

    original_image_bytes = choose_best_image_for_email(email_images)
    if not original_image_bytes:
        return None

    return generate_white_background_item_from_bytes(
        image_bytes=original_image_bytes,
        item_description=item_name,
    )



