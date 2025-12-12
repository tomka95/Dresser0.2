import quopri

from bs4 import BeautifulSoup


def clean_email_body(raw_body: str) -> str:
    """
    Decode quoted-printable, remove HTML tags, and normalize whitespace.
    Produces clean plaintext suitable for the heuristic parser.
    """
    if not raw_body:
        return ""

    # Step 1: decode quoted-printable artifacts (=3D, =E2=80=99, etc.)
    try:
        decoded = quopri.decodestring(raw_body).decode("utf-8", errors="ignore")
    except Exception:
        decoded = raw_body  # fallback

    # Step 2: strip HTML tags and get readable text
    try:
        soup = BeautifulSoup(decoded, "html.parser")
        text = soup.get_text("\n")  # preserve block structure
    except Exception:
        text = decoded  # fallback

    # Step 3: normalize whitespace and drop empty lines
    cleaned_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    return "\n".join(cleaned_lines)

