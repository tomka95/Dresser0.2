"""Local text-based search system for purchase-related emails."""

import difflib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class Email:
    """Email data model."""

    id: str
    subject: str
    body: str
    sender: Optional[str] = None
    date: Optional[str] = None


@dataclass
class ParsedClothingItem:
    """Parsed clothing item from an email."""

    store: Optional[str]
    brand: Optional[str]
    product_name: Optional[str]
    category: Optional[str]
    color: Optional[str]
    size: Optional[str]
    quantity: int
    price: Optional[float]
    currency: Optional[str]
    order_id: Optional[str]
    order_date: Optional[str]
    email_id: str
    image_alt: Optional[str] = None


# Clothing-related keywords for boosting relevance
CLOTHING_KEYWORDS: Set[str] = {
    "dress",
    "dresses",
    "jeans",
    "jean",
    "shirt",
    "shirts",
    "coat",
    "coats",
    "jacket",
    "jackets",
    "skirt",
    "skirts",
    "sneakers",
    "sneaker",
    "boots",
    "boot",
    "blazer",
    "blazers",
    "pants",
    "pant",
    "trousers",
    "trouser",
    "shorts",
    "short",
    "sweater",
    "sweaters",
    "hoodie",
    "hoodies",
    "cardigan",
    "cardigans",
    "t-shirt",
    "tshirt",
    "tshirts",
    "t-shirts",
    "top",
    "tops",
    "blouse",
    "blouses",
    "polo",
    "polos",
    "vest",
    "vests",
    "suit",
    "suits",
    "tie",
    "ties",
    "scarf",
    "scarves",
    "hat",
    "hats",
    "cap",
    "caps",
    "belt",
    "belts",
    "shoes",
    "shoe",
    "sandal",
    "sandals",
    "heels",
    "heel",
    "flats",
    "flat",
    "socks",
    "sock",
    "underwear",
    "bra",
    "bras",
    "lingerie",
    "swimwear",
    "bikini",
    "bikinis",
    "swimsuit",
    "swimsuits",
    "jewelry",
    "jewellery",
    "necklace",
    "necklaces",
    "bracelet",
    "bracelets",
    "earrings",
    "earring",
    "watch",
    "watches",
    "bag",
    "bags",
    "purse",
    "purses",
    "handbag",
    "handbags",
    "backpack",
    "backpacks",
    "wallet",
    "wallets",
    "gloves",
    "glove",
    "sunglasses",
    "sunglass",
    "jumper",
    "jumpers",
    "leggings",
    "legging",
    "yoga",
    "activewear",
    "sportswear",
    "athletic",
    "workout",
    "gym",
}


def normalize(text: str) -> str:
    """Normalize text by converting to lowercase and stripping whitespace.

    Args:
        text: Input text to normalize.

    Returns:
        Normalized text string.
    """
    return text.lower().strip()


def tokenize(text: str) -> List[str]:
    """Tokenize text into words, splitting on whitespace and punctuation.

    Args:
        text: Input text to tokenize.

    Returns:
        List of token strings.
    """
    normalized = normalize(text)
    # Split on whitespace and common punctuation
    tokens = []
    current_token = []
    for char in normalized:
        if char.isalnum():
            current_token.append(char)
        else:
            if current_token:
                tokens.append("".join(current_token))
                current_token = []
    if current_token:
        tokens.append("".join(current_token))
    return [t for t in tokens if t]


def token_set(text: str) -> Set[str]:
    """Convert text to a set of normalized tokens.

    Args:
        text: Input text to convert.

    Returns:
        Set of unique token strings.
    """
    return set(tokenize(text))


def token_overlap_score(set1: Set[str], set2: Set[str]) -> float:
    """Calculate Jaccard-like overlap score between two token sets.

    Args:
        set1: First set of tokens.
        set2: Second set of tokens.

    Returns:
        Overlap score between 0.0 and 1.0.
    """
    if not set1 or not set2:
        return 0.0

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    return intersection / union


def fuzzy_score(text1: str, text2: str) -> float:
    """Calculate fuzzy similarity score using difflib.SequenceMatcher.

    Args:
        text1: First text string.
        text2: Second text string.

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    if not text1 or not text2:
        return 0.0

    matcher = difflib.SequenceMatcher(None, normalize(text1), normalize(text2))
    return matcher.ratio()


def clothing_word_boost(text: str) -> float:
    """Calculate boost score based on clothing-related vocabulary presence.

    Args:
        text: Input text to analyze.

    Returns:
        Boost score between 0.0 and 0.5.
    """
    tokens = token_set(text)
    clothing_tokens = tokens & CLOTHING_KEYWORDS

    if not clothing_tokens:
        return 0.0

    # Boost up to 0.5 based on number of clothing keywords found
    # More keywords = higher boost, capped at 0.5
    num_keywords = len(clothing_tokens)
    boost = min(0.5, num_keywords * 0.1)

    return boost


def best_matching_line(email_body: str, query: str) -> Optional[str]:
    """Find the most relevant non-empty line in the email body for the query.

    Args:
        email_body: Full email body text.
        query: Search query string.

    Returns:
        Most relevant line, or None if no suitable line found.
    """
    if not email_body:
        return None

    query_tokens = token_set(query)
    lines = email_body.splitlines()

    best_line = None
    best_score = 0.0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        line_tokens = token_set(line)
        overlap = token_overlap_score(query_tokens, line_tokens)
        fuzzy = fuzzy_score(query, line)

        # Combined score for line relevance
        score = overlap * 0.6 + fuzzy * 0.4

        if score > best_score:
            best_score = score
            best_line = line

    return best_line


def score_email(email: Email, query: str) -> Tuple[float, Dict[str, float]]:
    """Score an email's relevance to a search query.

    Args:
        email: Email object to score.
        query: Search query string.

    Returns:
        Tuple of (score, debug_dict) where debug_dict contains component scores.
    """
    query_tokens = token_set(query)

    # Token overlap scores
    subject_tokens = token_set(email.subject)
    body_tokens = token_set(email.body)

    overlap_subject = token_overlap_score(query_tokens, subject_tokens)
    overlap_body = token_overlap_score(query_tokens, body_tokens)

    # Fuzzy similarity scores
    fuzzy_subject = fuzzy_score(query, email.subject)
    fuzzy_body = fuzzy_score(query, email.body)

    # Clothing word boost
    combined_text = f"{email.subject} {email.body}"
    clothing_boost = clothing_word_boost(combined_text)

    # Weighted combination
    score = (
        2.0 * overlap_subject
        + 1.0 * overlap_body
        + 0.7 * fuzzy_subject
        + 0.3 * fuzzy_body
        + clothing_boost
    )

    debug_dict = {
        "overlap_subject": overlap_subject,
        "overlap_body": overlap_body,
        "fuzzy_subject": fuzzy_subject,
        "fuzzy_body": fuzzy_body,
        "clothing_boost": clothing_boost,
        "final_score": score,
    }

    return score, debug_dict


def search_emails(
    query: str,
    emails: List[Email],
    top_k: int = 10,
    min_score: float = 0.3,
) -> List[Dict[str, Any]]:
    """Search emails and return top results sorted by relevance.

    Args:
        query: Search query string.
        emails: List of Email objects to search.
        top_k: Maximum number of results to return.
        min_score: Minimum score threshold for results.

    Returns:
        List of result dictionaries, each containing:
            - "email": Email object
            - "score": Relevance score
            - "best_line": Most relevant line from email body
            - "debug": Dictionary of component scores
    """
    if not query or not emails:
        return []

    results = []

    for email in emails:
        score, debug = score_email(email, query)

        if score >= min_score:
            best_line = best_matching_line(email.body, query)
            results.append(
                {
                    "email": email,
                    "score": score,
                    "best_line": best_line,
                    "debug": debug,
                }
            )

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Return top_k results
    return results[:top_k]

