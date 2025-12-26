"""Heuristic parser for extracting clothing purchase items from plain-text emails."""

import re
from typing import List, Optional, Tuple

from .email_smart_search import CLOTHING_KEYWORDS, Email, ParsedClothingItem

# Common color names for detection
COLOR_KEYWORDS = {
    "black",
    "white",
    "red",
    "blue",
    "green",
    "yellow",
    "orange",
    "purple",
    "pink",
    "brown",
    "gray",
    "grey",
    "beige",
    "navy",
    "maroon",
    "burgundy",
    "tan",
    "khaki",
    "olive",
    "coral",
    "teal",
    "turquoise",
    "lavender",
    "ivory",
    "cream",
    "gold",
    "silver",
    "bronze",
    "copper",
}

# Common size patterns
SIZE_PATTERNS = {
    "xs",
    "s",
    "m",
    "l",
    "xl",
    "xxl",
    "xxxl",
    "us",
    "eu",
    "uk",
}

# Currency symbols and codes
CURRENCY_SYMBOLS = {"$", "€", "£", "¥", "₹", "₽", "₪"}
CURRENCY_CODES = {"usd", "eur", "gbp", "jpy", "cad", "aud", "inr", "rub", "ils"}

# Generic email providers to ignore when extracting store names
GENERIC_EMAIL_PROVIDERS = {
    "gmail",
    "yahoo",
    "outlook",
    "hotmail",
    "live",
    "msn",
    "aol",
    "icloud",
    "mail",
    "email",
}

# Generic technical prefixes to ignore in multi-part domains
GENERIC_DOMAIN_PREFIXES = {
    "e",
    "mail",
    "email",
    "news",
    "info",
    "noreply",
    "no-reply",
    "support",
    "help",
    "contact",
}

# Keywords that indicate non-clothing lines (order totals, shipping, etc.)
NON_CLOTHING_KEYWORDS = {
    "order total",
    "subtotal",
    "tax",
    "shipping",
    "delivery",
    "handling",
    "discount",
    "coupon",
    "promo",
    "refund",
    "return",
    "exchange",
    "gift card",
    "gift wrap",
    "service fee",
    "processing fee",
    "total amount",
    "amount due",
    "balance",
    "payment",
    "transaction fee",
}


def _extract_store_from_domain(domain: str) -> Optional[str]:
    """Extract store name from a domain, handling multi-part domains.

    Args:
        domain: Domain string (e.g., "e.lululemon.com" or "lululemon.com").

    Returns:
        Store name string, or None if domain is generic.
    """
    # Split domain into parts
    parts = domain.split(".")
    if len(parts) < 2:
        return None

    # Remove TLD (last part) and reverse to process from right to left
    domain_parts = parts[:-1]
    domain_parts.reverse()

    # Find the first non-generic segment
    for part in domain_parts:
        part_lower = part.lower()
        if part_lower not in GENERIC_EMAIL_PROVIDERS and part_lower not in GENERIC_DOMAIN_PREFIXES:
            # Found a non-generic segment - this is likely the brand
            return part.capitalize()

    return None


def extract_store_name(email: Email) -> Optional[str]:
    """Extract store name from email sender, subject, or body.

    Handles forwarded emails by extracting the original sender from the body.
    Handles multi-part domains by ignoring generic prefixes.

    Args:
        email: Email object to extract store name from.

    Returns:
        Store name string, or None if not found.
    """
    # Check if this is a forwarded email
    is_forwarded = email.subject and email.subject.lower().startswith(("fwd:", "fw:"))

    if is_forwarded and email.body:
        # Extract original sender from forwarded email body
        lines = email.body.split("\n")[:40]  # Check first 40 lines
        for line in lines:
            line = line.strip()
            if line.lower().startswith("from:"):
                # Extract sender from "From: orders@lululemon.com" or "From: Lululemon <noreply@e.lululemon.com>"
                from_match = re.search(r"from:\s*(.+)", line, re.IGNORECASE)
                if from_match:
                    sender_text = from_match.group(1).strip()

                    # Try to extract email from angle brackets
                    email_match = re.search(r"<([^>]+)>", sender_text)
                    if email_match:
                        sender_email = email_match.group(1)
                    else:
                        # No angle brackets, use the text directly
                        sender_email = sender_text

                    # Extract full domain from sender email (e.g., "e.lululemon.com")
                    domain_match = re.search(r"@([a-zA-Z0-9.-]+)", sender_email.lower())
                    if domain_match:
                        full_domain = domain_match.group(1)
                        store = _extract_store_from_domain(full_domain)
                        if store:
                            # Handle common variations
                            if store in ["Zara", "Hm", "Asos", "Nike", "Adidas"]:
                                return store
                            return store

                    # Try to extract store name from sender text (before <)
                    name_match = re.search(r"^([^<]+)", sender_text)
                    if name_match:
                        name = name_match.group(1).strip()
                        if name and len(name) < 50:
                            return name

    # Regular email: try to extract from sender email domain
    if email.sender:
        # Extract full domain (e.g., "e.lululemon.com" or "zara.com")
        domain_match = re.search(r"@([a-zA-Z0-9.-]+)", email.sender.lower())
        if domain_match:
            full_domain = domain_match.group(1)
            store = _extract_store_from_domain(full_domain)
            if store:
                return store

        # Try to extract from sender name: "Zara <orders@zara.com>"
        name_match = re.search(r"^([^<]+)<", email.sender)
        if name_match:
            name = name_match.group(1).strip()
            if name:
                return name

    # Try to extract from subject
    if email.subject:
        # Look for common patterns: "Your order from Zara", "Zara Order Confirmation"
        patterns = [
            r"from\s+([A-Z][a-zA-Z0-9\s&]+?)(?:\s+order|\s+receipt|$)",
            r"^([A-Z][a-zA-Z0-9\s&]+?)(?:\s+order|\s+receipt|\s+confirmation)",
            r"order\s+from\s+([A-Z][a-zA-Z0-9\s&]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, email.subject, re.IGNORECASE)
            if match:
                store = match.group(1).strip()
                if len(store) < 50:  # Reasonable store name length
                    return store

    # Try to extract from first few lines of body
    if email.body:
        lines = email.body.split("\n")[:5]  # Check first 5 lines
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Look for "Store:" or "Retailer:" patterns
            store_match = re.search(
                r"(?:store|retailer|merchant)[:\s]+([A-Z][a-zA-Z0-9\s&]+)",
                line,
                re.IGNORECASE,
            )
            if store_match:
                store = store_match.group(1).strip()
                if len(store) < 50:
                    return store

    return None


def extract_order_id(email: Email) -> Optional[str]:
    """Extract order ID from email subject or body.

    Args:
        email: Email object to extract order ID from.

    Returns:
        Order ID string, or None if not found.
    """
    text_to_search = f"{email.subject} {email.body}"

    # Common order ID patterns
    patterns = [
        r"order\s*#\s*([A-Z0-9-]+)",
        r"order\s+id[:\s]+([A-Z0-9-]+)",
        r"order\s+no[.:\s]+([A-Z0-9-]+)",
        r"order\s+number[:\s]+([A-Z0-9-]+)",
        r"order[:\s]+([A-Z0-9-]{6,})",  # Generic order followed by alphanumeric
        r"confirmation[:\s]+([A-Z0-9-]+)",
        r"#\s*([A-Z0-9-]{6,})",  # Standalone # followed by alphanumeric
    ]

    for pattern in patterns:
        match = re.search(pattern, text_to_search, re.IGNORECASE)
        if match:
            order_id = match.group(1).strip()
            if len(order_id) >= 3:  # Reasonable minimum length
                return order_id

    return None


def extract_order_date(email: Email) -> Optional[str]:
    """Extract order date from email subject or body.

    Args:
        email: Email object to extract order date from.

    Returns:
        Order date string, or None if not found.
    """
    text_to_search = f"{email.subject} {email.body}"

    # Common date patterns
    patterns = [
        r"date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"order\s+date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"purchased[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",  # Generic date pattern
        r"(\d{4}-\d{2}-\d{2})",  # ISO format
    ]

    for pattern in patterns:
        match = re.search(pattern, text_to_search, re.IGNORECASE)
        if match:
            date_str = match.group(1).strip()
            return date_str

    # If email has a date field, use it
    if email.date:
        return email.date

    return None


def extract_price_and_currency(text: str) -> Tuple[Optional[float], Optional[str]]:
    """Extract price and currency from text.

    Supports multiple currency formats including ILS, CAD, and decimal separators.

    Args:
        text: Text string to extract price from.

    Returns:
        Tuple of (price, currency) or (None, None) if not found.
    """
    # First pass: symbol-based patterns
    SYMBOL_PATTERN = re.compile(
        r"""
        (?P<symbol>[$€£₪])
        \s*
        (?P<amount>\d{1,6}(?:[.,]\d{2})?)
        """,
        re.VERBOSE,
    )

    # Also handle CA$64.00 format
    ca_symbol_pattern = re.compile(
        r"CA\s*(?P<symbol>[$])\s*(?P<amount>\d{1,6}(?:[.,]\d{2})?)",
        re.IGNORECASE | re.VERBOSE,
    )

    match = ca_symbol_pattern.search(text)
    if match:
        currency_symbol = match.group("symbol")
        price_str = match.group("amount")
        price_str = price_str.replace(",", ".")
        try:
            price = float(price_str)
            currency_map = {
                "$": "USD",
                "€": "EUR",
                "£": "GBP",
                "₪": "ILS",
            }
            currency = currency_map.get(currency_symbol, currency_symbol)
            return price, currency
        except ValueError:
            pass

    match = SYMBOL_PATTERN.search(text)
    if match:
        currency_symbol = match.group("symbol")
        price_str = match.group("amount")
        price_str = price_str.replace(",", ".")
        try:
            price = float(price_str)
            currency_map = {
                "$": "USD",
                "€": "EUR",
                "£": "GBP",
                "₪": "ILS",
            }
            currency = currency_map.get(currency_symbol, currency_symbol)
            return price, currency
        except ValueError:
            pass

    # Second pass: code-based patterns (including ILS)
    CODE_PATTERN = re.compile(
        r"""
        (?P<code>(USD|EUR|GBP|CAD|AUD|ILS))
        \s*
        (?P<amount>\d{1,6}(?:[.,]\d{2})?)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    match = CODE_PATTERN.search(text)
    if match:
        currency = match.group("code").upper()
        price_str = match.group("amount")
        price_str = price_str.replace(",", ".")
        try:
            price = float(price_str)
            return price, currency
        except ValueError:
            pass

    # Also handle code after amount: "98.00 USD", "425.22 ILS", "98,00 EUR"
    CODE_AFTER_PATTERN = re.compile(
        r"""
        (?P<amount>\d{1,6}(?:[.,]\d{2})?)
        \s*
        (?P<code>(USD|EUR|GBP|CAD|AUD|ILS))
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    match = CODE_AFTER_PATTERN.search(text)
    if match:
        currency = match.group("code").upper()
        price_str = match.group("amount")
        price_str = price_str.replace(",", ".")
        try:
            price = float(price_str)
            return price, currency
        except ValueError:
            pass

    # Also handle no-space format: "USD98", "ILS425"
    CODE_NO_SPACE_PATTERN = re.compile(
        r"""
        (?P<code>(USD|EUR|GBP|CAD|AUD|ILS))
        (?P<amount>\d{1,6}(?:[.,]\d{2})?)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    match = CODE_NO_SPACE_PATTERN.search(text)
    if match:
        currency = match.group("code").upper()
        price_str = match.group("amount")
        price_str = price_str.replace(",", ".")
        try:
            price = float(price_str)
            return price, currency
        except ValueError:
            pass

    # Fallback: bare amount with decimals
    price_pattern = r"(\d+[.,]\d{2})\b"
    match = re.search(price_pattern, text)
    if match:
        try:
            price_str = match.group(1).replace(",", ".")
            price = float(price_str)
            return price, None  # Currency unknown
        except ValueError:
            pass

    return None, None


def find_price_near_product_name(
    body: str, product_name: str
) -> Tuple[Optional[float], Optional[str]]:
    """Search the email body near a product name for a price and currency.

    Strategy:
    - Find the first occurrence of the product_name (case-insensitive).
    - Take a window of text starting at that position.
    - Within that window, look for price patterns with a currency symbol
      (e.g. "$64.00") or currency code (e.g. "USD 64.00").
    - Return the last price match found in the window (usually the discounted / final).

    Args:
        body: Full email body text.
        product_name: Product name to search for.

    Returns:
        Tuple of (price, currency) or (None, None) if not found.
    """
    if not body or not product_name:
        return None, None

    try:
        body_lower = body.lower()
        name_lower = product_name.lower()
    except Exception:
        return None, None

    idx = body_lower.find(name_lower)
    if idx == -1:
        return None, None

    # Look in a window after the product name; adjust size if needed
    window = body[idx : idx + 400]

    # Match currency symbols like $64.00, €59.99, ₪128, etc.
    symbol_pattern = re.compile(r"([$€£¥₹₽₪])\s*(\d+(?:[.,]\d{2})?)")

    # Match currency codes like "USD 64.00"
    code_pattern = re.compile(
        r"\b(USD|EUR|GBP|JPY|CAD|AUD|INR|RUB|ILS)\s*(\d+(?:[.,]\d{2})?)",
        re.IGNORECASE,
    )

    currency: Optional[str] = None
    price: Optional[float] = None

    # Currency symbol to code mapping
    currency_map = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
        "₽": "RUB",
        "₪": "ILS",
    }

    # Take the last symbol match in the window (often the final price)
    for match in symbol_pattern.finditer(window):
        symbol, amount_str = match.groups()
        try:
            amount = float(amount_str.replace(",", "."))
        except (TypeError, ValueError):
            continue
        currency = currency_map.get(symbol, symbol)
        price = amount

    # Also consider code-based currencies (e.g. "USD 425.22")
    for match in code_pattern.finditer(window):
        code, amount_str = match.groups()
        try:
            amount = float(amount_str.replace(",", "."))
        except (TypeError, ValueError):
            continue
        currency = code.upper()
        price = amount

    return price, currency


def extract_quantity(text: str) -> int:
    """Extract quantity from text (e.g., "2x", "x2", "2 x").

    Args:
        text: Text string to extract quantity from.

    Returns:
        Quantity as integer, defaults to 1 if not found.
    """
    # Patterns: "2x", "x2", "2 x", "Qty: 2", "Quantity: 2"
    patterns = [
        r"(\d+)\s*x\b",
        r"x\s*(\d+)",
        r"qty[:\s]+(\d+)",
        r"quantity[:\s]+(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

    return 1  # Default quantity


def extract_size(text: str) -> Optional[str]:
    """Extract size from text.

    Args:
        text: Text string to extract size from.

    Returns:
        Size string, or None if not found.
    """
    # Pattern: "Size: M", "Size M", "S", "M", "L", "XL", etc.
    size_pattern = r"size[:\s]+([A-Z0-9]+(?:\/[A-Z0-9]+)?)"
    match = re.search(size_pattern, text, re.IGNORECASE)
    if match:
        size = match.group(1).upper()
        return size

    # Look for standalone size tokens
    words = re.findall(r"\b([A-Z0-9]+)\b", text.upper())
    for word in words:
        if word in SIZE_PATTERNS or re.match(r"^(XS|S|M|L|XL|XXL|XXXL)$", word):
            return word
        # Numeric sizes: 34, 36, 38, etc.
        if re.match(r"^\d{2,3}$", word) and 20 <= int(word) <= 60:
            return word

    return None


def extract_color(text: str) -> Optional[str]:
    """Extract color from text.

    Args:
        text: Text string to extract color from.

    Returns:
        Color string, or None if not found.
    """
    # Pattern: "Color: Black", "Color Black"
    color_pattern = r"color[:\s]+([a-zA-Z]+)"
    match = re.search(color_pattern, text, re.IGNORECASE)
    if match:
        color = match.group(1).lower()
        if color in COLOR_KEYWORDS:
            return color.capitalize()

    # Look for color keywords in text
    text_lower = text.lower()
    for color in COLOR_KEYWORDS:
        if re.search(rf"\b{color}\b", text_lower):
            return color.capitalize()

    return None


def extract_image_alt_text(line: str) -> Optional[str]:
    """Extract image alt text from a line containing an image tag.

    Args:
        line: Text line that may contain an image tag.

    Returns:
        Alt text string if found, None otherwise.
    """
    # Pattern for [image: ...] format (case-insensitive)
    image_pattern = r'^\s*\[image:\s*(.+?)\]\s*$'
    match = re.search(image_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Pattern for HTML img tags: <img alt="...">
    img_pattern = r'<img[^>]*alt=["\']([^"\']+)["\']'
    match = re.search(img_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Pattern for markdown-style images: ![alt text](url)
    markdown_pattern = r'!\[([^\]]+)\]'
    match = re.search(markdown_pattern, line)
    if match:
        return match.group(1).strip()

    return None


def is_non_clothing_line(line: str) -> bool:
    """Check if a line is a non-clothing line (order totals, shipping, etc.).

    Args:
        line: Text line to check.

    Returns:
        True if line is a non-clothing line that should be filtered out.
    """
    line_lower = line.lower()

    # Check for non-clothing keywords
    for keyword in NON_CLOTHING_KEYWORDS:
        if keyword in line_lower:
            return True

    # Check for patterns like "Order Total:", "Subtotal:", "Tax:", "Shipping:"
    non_clothing_patterns = [
        r"^(order\s+)?total[:\s]",
        r"subtotal[:\s]",
        r"^tax[:\s]",
        r"shipping[:\s]",
        r"delivery[:\s]",
        r"handling[:\s]",
        r"discount[:\s]",
        r"coupon[:\s]",
        r"promo[:\s]",
        r"refund[:\s]",
        r"return[:\s]",
        r"exchange[:\s]",
        r"gift\s+card[:\s]",
        r"gift\s+wrap[:\s]",
        r"service\s+fee[:\s]",
        r"processing\s+fee[:\s]",
        r"amount\s+due[:\s]",
        r"balance[:\s]",
        r"payment[:\s]",
        r"transaction\s+fee[:\s]",
    ]

    for pattern in non_clothing_patterns:
        if re.search(pattern, line_lower):
            return True

    return False


def is_pure_size_or_code(line: str) -> bool:
    """Return True if the line looks like only a size/code (e.g. 'CN39', 'M', 'XL'), not a full product description.

    Args:
        line: Text line to check.

    Returns:
        True if line is just a size or code, False otherwise.
    """
    stripped = line.strip().lower()

    if not stripped:
        return False

    # Common standalone sizes
    SIMPLE_SIZES = {"xs", "s", "m", "l", "xl", "xxl", "xxxl"}

    if stripped in SIMPLE_SIZES:
        return True

    # Code patterns like CN39, EU38, US6
    if re.fullmatch(r"[a-z]{1,3}\d{1,3}", stripped):
        return True

    return False


def is_clothing_related_line(line: str) -> bool:
    """Check if a line is likely related to clothing items.

    Returns True ONLY if the line contains at least one actual clothing keyword.

    Args:
        line: Text line to check.

    Returns:
        True if line contains clothing keywords, False otherwise.
    """
    line_lower = line.lower()
    tokens = set(re.findall(r"\b\w+\b", line_lower))

    # Return True ONLY if tokens intersect with CLOTHING_KEYWORDS
    return bool(tokens & CLOTHING_KEYWORDS)


def is_valid_item(parsed: dict) -> bool:
    """Check if a parsed item is valid (not garbage).

    Filters out items with no meaningful name or price.

    Args:
        parsed: Dictionary with parsed item fields.

    Returns:
        True if item is valid, False if it should be filtered out.
    """
    product_name = parsed.get("product_name", "")

    # Filter out items with no product name or very short names
    if not product_name or len(product_name.strip()) < 2:
        return False

    # Filter out items that are just codes/numbers without meaningful text
    # e.g., "CN39", "12345", "ABC123"
    if re.match(r"^[A-Z0-9]{1,10}$", product_name.strip()):
        # If it's just a code and has no price, it's garbage
        if parsed.get("price") is None:
            return False

    # Filter out items with no price and no meaningful name
    if parsed.get("price") is None:
        # Must have a meaningful product name (not just codes)
        if len(product_name.strip()) < 5:
            return False

    return True


def parse_line_item(name_line: str, context_lines: Optional[List[str]] = None) -> Optional[dict]:
    """Parse a line item to extract clothing item details.

    Can use context lines (e.g., following lines in a block) to extract price
    and other details that may be on separate lines.

    Args:
        name_line: The main product name line to parse.
        context_lines: Optional list of additional lines to scan for price/size/color.

    Returns:
        Dictionary with parsed fields, or None if not a valid item.
    """
    name_line = name_line.strip()
    if not name_line or len(name_line) < 3:
        return None

    # Combine name_line and context_lines for price extraction
    if context_lines:
        block_text = " ".join([name_line] + context_lines)
    else:
        block_text = name_line

    # Extract components from the block
    quantity = extract_quantity(block_text)
    # Extract price from block_text - if multiple prices, take the last one (discounted price)
    price, currency = _extract_price_from_block(block_text)
    size = extract_size(block_text)
    color = extract_color(block_text)

    # Extract product name - remove extracted components
    product_name = name_line

    # Remove quantity patterns
    product_name = re.sub(r"\d+\s*x\b", "", product_name, flags=re.IGNORECASE)
    product_name = re.sub(r"x\s*\d+", "", product_name, flags=re.IGNORECASE)
    product_name = re.sub(r"qty[:\s]+\d+", "", product_name, flags=re.IGNORECASE)
    product_name = re.sub(r"quantity[:\s]+\d+", "", product_name, flags=re.IGNORECASE)

    # Remove price patterns (updated to handle all currency formats)
    product_name = re.sub(r"CA\s*[$]\s*\d+(?:[.,]\d{2,})?", "", product_name, re.IGNORECASE)
    product_name = re.sub(r"[$€£¥₹₽₪]\s*\d+(?:[.,]\d{2,})?", "", product_name)
    product_name = re.sub(
        r"(USD|EUR|GBP|JPY|CAD|AUD|INR|RUB|ILS)\s*\d+(?:[.,]\d{2,})?",
        "",
        product_name,
        flags=re.IGNORECASE,
    )
    product_name = re.sub(
        r"\d+(?:[.,]\d{2,})?\s*(USD|EUR|GBP|JPY|CAD|AUD|INR|RUB|ILS)",
        "",
        product_name,
        flags=re.IGNORECASE,
    )
    product_name = re.sub(r"(USD|EUR|GBP|JPY|CAD|AUD|INR|RUB|ILS)\d+(?:[.,]\d{2,})?", "", product_name, flags=re.IGNORECASE)
    product_name = re.sub(r"\d+[.,]\d{2}\b", "", product_name)

    # Remove size patterns
    if size:
        product_name = re.sub(rf"size[:\s]+{re.escape(size)}", "", product_name, flags=re.IGNORECASE)
        product_name = re.sub(rf"\b{re.escape(size)}\b", "", product_name)

    # Remove color patterns
    if color:
        product_name = re.sub(rf"color[:\s]+{re.escape(color.lower())}", "", product_name, flags=re.IGNORECASE)
        product_name = re.sub(rf"\b{re.escape(color.lower())}\b", "", product_name)

    # Clean up product name
    product_name = re.sub(r"\s+", " ", product_name).strip()
    product_name = re.sub(r"^[:\-\s]+|[:\-\s]+$", "", product_name)

    # If we have a price or clothing keywords, consider it a valid item
    if price is not None or is_clothing_related_line(name_line):
        parsed_dict = {
            "product_name": product_name if product_name else None,
            "quantity": quantity,
            "size": size,
            "color": color,
            "price": price,
            "currency": currency,
        }
        # Filter out garbage items
        if is_valid_item(parsed_dict):
            return parsed_dict

    return None


def _extract_price_from_block(block_text: str) -> Tuple[Optional[float], Optional[str]]:
    """Extract price from block text, taking the last price if multiple exist.

    This handles cases like "$64.00 $39.00" where we want the discounted price (last one).

    Args:
        block_text: Combined text from multiple lines.

    Returns:
        Tuple of (price, currency) or (None, None) if not found.
    """
    # Find all price matches in the block
    price_matches = []
    
    # Try symbol patterns
    symbol_pattern = re.compile(
        r"""
        ([$€£₪])
        \s*
        (\d{1,6}(?:[.,]\d{2})?)
        """,
        re.VERBOSE,
    )
    
    for match in symbol_pattern.finditer(block_text):
        currency_symbol = match.group(1)
        price_str = match.group(2).replace(",", ".")
        try:
            price = float(price_str)
            currency_map = {
                "$": "USD",
                "€": "EUR",
                "£": "GBP",
                "₪": "ILS",
            }
            currency = currency_map.get(currency_symbol, currency_symbol)
            price_matches.append((price, currency, match.end()))
        except ValueError:
            pass
    
    # Try code patterns - code first: USD 98.00
    code_first_pattern = re.compile(
        r"""
        (USD|EUR|GBP|CAD|AUD|ILS)
        \s*
        (\d{1,6}(?:[.,]\d{2})?)
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    
    for match in code_first_pattern.finditer(block_text):
        currency = match.group(1).upper()
        price_str = match.group(2).replace(",", ".")
        try:
            price = float(price_str)
            price_matches.append((price, currency, match.end()))
        except ValueError:
            pass
    
    # Try code patterns - code last: 98.00 USD
    code_last_pattern = re.compile(
        r"""
        (\d{1,6}(?:[.,]\d{2})?)
        \s*
        (USD|EUR|GBP|CAD|AUD|ILS)
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    
    for match in code_last_pattern.finditer(block_text):
        price_str = match.group(1).replace(",", ".")
        currency = match.group(2).upper()
        try:
            price = float(price_str)
            price_matches.append((price, currency, match.end()))
        except ValueError:
            pass
    
    # Try code patterns - no space: USD98
    code_no_space_pattern = re.compile(
        r"""
        (USD|EUR|GBP|CAD|AUD|ILS)
        (\d{1,6}(?:[.,]\d{2})?)
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    
    for match in code_no_space_pattern.finditer(block_text):
        currency = match.group(1).upper()
        price_str = match.group(2).replace(",", ".")
        try:
            price = float(price_str)
            price_matches.append((price, currency, match.end()))
        except ValueError:
            pass
    
    # If we found multiple prices, return the last one (discounted price)
    if price_matches:
        # Sort by position in text (end position) and take the last
        price_matches.sort(key=lambda x: x[2])
        last_price, last_currency, _ = price_matches[-1]
        return last_price, last_currency
    
    # Fallback to single price extraction
    return extract_price_and_currency(block_text)


def parse_clothing_items_from_email(email: Email) -> List[ParsedClothingItem]:
    """Parse clothing purchase items from a plain-text email.

    This function uses heuristics to extract clothing items, order metadata,
    and item details from email content. It handles image alt text extraction
    and filters out non-clothing lines and garbage items.

    Args:
        email: Email object containing subject, body, sender, etc.

    Returns:
        List of ParsedClothingItem objects, one per detected line item.
    """
    items = []

    # Extract metadata
    store = extract_store_name(email)
    order_id = extract_order_id(email)
    order_date = extract_order_date(email)

    # Split body into lines and process
    lines = [line.strip() for line in email.body.split("\n")]
    clothing_blocks = []  # List of (name_line_index, context_lines, image_alt)
    pending_image_alt: Optional[str] = None

    # First pass: identify clothing-related lines (block starts) and extract image alt text
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        # Skip pure size/code lines
        if is_pure_size_or_code(line):
            i += 1
            continue

        # Check for image alt text (including [image: ...] pattern)
        image_alt = extract_image_alt_text(line)
        if image_alt:
            # Store for next legitimate clothing item
            pending_image_alt = image_alt
            i += 1
            continue

        # Check if line is clothing-related first
        is_clothing = is_clothing_related_line(line)

        # Filter out non-clothing lines (order totals, shipping, etc.)
        # Only filter if the line is NOT clothing-related
        if not is_clothing and is_non_clothing_line(line):
            i += 1
            continue

        # ONLY process clothing-related lines as block starts
        if is_clothing:
            # Collect context lines (up to 3 following lines)
            # These may contain quantity, SKU, size, color, and price information
            context_lines = []
            for j in range(i + 1, min(i + 4, len(lines))):
                context_line = lines[j]
                # Stop if we hit an empty line or another clothing-related line (start of next item)
                if not context_line or is_clothing_related_line(context_line):
                    break
                # Include all context lines (even size/code lines) as they may contain price info
                context_lines.append(context_line)

            clothing_blocks.append((i, context_lines, pending_image_alt))
            # Reset pending image alt after attaching to a block
            pending_image_alt = None
            # Skip past the context lines we just collected
            i += 1 + len(context_lines)
        else:
            i += 1

    # Second pass: parse each clothing-related block
    for name_line_idx, context_lines, image_alt in clothing_blocks:
        name_line = lines[name_line_idx]

        parsed = parse_line_item(name_line, context_lines)
        if parsed:
            item = ParsedClothingItem(
                store=store,
                brand=None,  # Brand extraction could be added later
                product_name=parsed["product_name"],
                category=None,  # Category could be inferred from keywords
                color=parsed["color"],
                size=parsed["size"],
                quantity=parsed["quantity"],
                price=parsed["price"],
                currency=parsed["currency"],
                order_id=order_id,
                order_date=order_date,
                email_id=email.id,
                image_alt=image_alt,
            )
            items.append(item)

    # If we have items but some are missing price, try to infer a price
    # by looking near the product name in the full email body.
    if items:
        for item in items:
            if item.price is None and item.product_name:
                inferred_price, inferred_currency = find_price_near_product_name(
                    email.body, item.product_name
                )
                if inferred_price is not None:
                    item.price = inferred_price
                    item.currency = inferred_currency

    # If no items found but email seems purchase-related, try parsing all lines
    if not items and (order_id or store or re.search(r"order|purchase|receipt", email.body, re.IGNORECASE)):
        # Fallback: try parsing lines with prices, but ONLY if clothing-related
        # Use block-aware parsing here too
        pending_image_alt = None
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line:
                i += 1
                continue

            # Skip pure size/code lines
            if is_pure_size_or_code(line):
                i += 1
                continue

            # Check for image alt text (including [image: ...] pattern)
            image_alt = extract_image_alt_text(line)
            if image_alt:
                pending_image_alt = image_alt
                i += 1
                continue

            # Check if line is clothing-related first
            is_clothing = is_clothing_related_line(line)

            # Filter out non-clothing lines (order totals, shipping, etc.)
            # Only filter if the line is NOT clothing-related
            if not is_clothing and is_non_clothing_line(line):
                i += 1
                continue

            # ONLY consider clothing-related lines
            if is_clothing and len(line) > 10:
                # Collect context lines (up to 3 following lines)
                # These may contain quantity, SKU, size, color, and price information
                context_lines = []
                for j in range(i + 1, min(i + 4, len(lines))):
                    context_line = lines[j]
                    # Stop if we hit an empty line or another clothing-related line (start of next item)
                    if not context_line or is_clothing_related_line(context_line):
                        break
                    # Include all context lines (even size/code lines) as they may contain price info
                    context_lines.append(context_line)

                parsed = parse_line_item(line, context_lines)
                if parsed and parsed["product_name"]:
                    item = ParsedClothingItem(
                        store=store,
                        brand=None,
                        product_name=parsed["product_name"],
                        category=None,
                        color=parsed["color"],
                        size=parsed["size"],
                        quantity=parsed["quantity"],
                        price=parsed["price"],
                        currency=parsed["currency"],
                        order_id=order_id,
                        order_date=order_date,
                        email_id=email.id,
                        image_alt=pending_image_alt,
                    )
                    items.append(item)
                    pending_image_alt = None
                    # Skip past the context lines
                    i += 1 + len(context_lines)
                else:
                    i += 1
            else:
                i += 1

    return items

