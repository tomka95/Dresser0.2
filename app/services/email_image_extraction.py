import base64
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass
class EmailImages:
    """Container for images associated with an email."""

    html_body: str  # raw HTML body of the email
    inline_images: List[bytes]  # decoded inline/attachment images


def extract_first_http_link_from_html(html: str) -> Optional[str]:
    """Return the first http(s) link in the email HTML, or None."""
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http://") or href.startswith("https://"):
            return href

    return None


def _download_image_bytes(url: str, timeout: int = 10) -> Optional[bytes]:
    """Download an image and return its bytes, or None on failure."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


def fetch_product_image_from_url(url: str) -> Optional[bytes]:
    """
    Given a product / order link, try to find the primary product image.

    Strategy:
    1. Look for og:image meta tag.
    2. Fallback: first <img> tag.
    """
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1) og:image
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        img_url = urljoin(url, og_image["content"])
        img_bytes = _download_image_bytes(img_url)
        if img_bytes:
            return img_bytes

    # 2) fallback: first <img>
    first_img = soup.find("img")
    if first_img and first_img.get("src"):
        img_url = urljoin(url, first_img["src"])
        img_bytes = _download_image_bytes(img_url)
        if img_bytes:
            return img_bytes

    return None


def choose_best_image_for_email(email_images: EmailImages) -> Optional[bytes]:
    """
    Implements your rule:
    1) If there's a link in the email, try extracting the image from there.
    2) If that fails, fall back to inline/attachment images.
    """
    # 1) Try website image
    link = extract_first_http_link_from_html(email_images.html_body)
    if link:
        image_bytes = fetch_product_image_from_url(link)
        if image_bytes:
            return image_bytes

    # 2) Try inline email images
    if email_images.inline_images:
        return email_images.inline_images[0]

    return None



