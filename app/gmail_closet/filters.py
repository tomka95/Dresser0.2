"""Deterministic filters to identify potential clothing purchase emails."""

from .models import EmailMetadata

PURCHASE_SUBJECT_KEYWORDS = [
    "order",
    "receipt",
    "confirmation",
    "invoice",
    "purchase",
    "shipped",
    "delivery",
]

# Keywords that indicate clothing/accessories
CLOTHING_KEYWORDS = [
    "jeans",
    "pants",
    "trousers",
    "dress",
    "shirt",
    "t-shirt",
    "tee",
    "skirt",
    "coat",
    "jacket",
    "hoodie",
    "sweater",
    "cardigan",
    "sneakers",
    "boots",
    "shoes",
    "sandals",
    "bag",
    "handbag",
    "backpack",
    "belt",
    "scarf",
    "hat",
    "cap",
    "gloves",
    "bra",
    "underwear",
    "lingerie",
    "socks",
    "jewelry",
    "watch",
    "sunglasses",
    "accessories",
    "apparel",
    "clothing",
    "fashion",
    "outfit",
    "wardrobe",
    "garment",
    "top",
    "bottom",
    "blouse",
    "polo",
    "tank",
    "tank top",
    "shorts",
    "sweatshirt",
    "jumper",
    "blazer",
    "vest",
    "pajamas",
    "pajama",
    "robe",
    "slippers",
    "heels",
    "flats",
    "loafers",
    "sneaker",
    "boot",
    "purse",
    "wallet",
    "necklace",
    "bracelet",
    "earrings",
    "ring",
]

# Keywords that indicate non-clothing purchases
NON_CLOTHING_KEYWORDS = [
    "gas bill",
    "electricity",
    "water bill",
    "invoice for services",
    "flight",
    "hotel",
    "uber",
    "lyft",
    "subscription",
    "software",
    "app store",
    "grocery",
    "supermarket",
    "food delivery",
    "restaurant",
    "cafe",
    "coffee",
    "movie",
    "ticket",
    "event",
    "parking",
    "utilities",
    "phone bill",
    "internet",
    "cable",
    "streaming",
    "netflix",
    "spotify",
    "amazon prime",
    "furniture",
    "appliance",
    "electronics",
    "computer",
    "laptop",
    "phone",
    "tablet",
    "book",
    "ebook",
    "magazine",
]


def is_potential_clothing_email(metadata: EmailMetadata, body_text: str) -> bool:
    """Return True if this email is likely a purchase/receipt email.

    New logic:
    - We ONLY check the SUBJECT for purchase-related keywords like "order", "receipt".
    - We NO LONGER require clothing keywords in subject/body.
    - We DO NOT block based on non-clothing keywords.
    - The LLM is responsible for deciding whether it contains clothing items.

    Args:
        metadata: Email metadata including subject and sender.
        body_text: Plain text body of the email.

    Returns:
        True if the email subject contains purchase-related keywords, False otherwise.
    """
    subject_lower = metadata.subject.lower()

    # Require at least one purchase-related keyword in the subject
    has_purchase_keyword = any(
        keyword in subject_lower for keyword in PURCHASE_SUBJECT_KEYWORDS
    )

    return has_purchase_keyword

