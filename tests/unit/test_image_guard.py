"""Unit tests for the SSRF guard (app.gmail_closet.image_guard).

These are fully self-contained — no real DNS or network. DNS is injected via the
``resolver`` parameter so we can simulate a public host that "rebinds" to a private
address. The two headline confirmations the image-backfill status report depends on:

  (a) a non-allow-listed domain is REFUSED (before any DNS / packet), and
  (b) an allow-listed host that resolves to a private / metadata IP is REFUSED.

are ``test_reject_non_allowlisted_domain`` and ``test_reject_private_ip_rebind`` /
``test_reject_metadata_ip`` below.
"""
import httpx
import pytest

from app.gmail_closet import image_guard as g
from app.gmail_closet.image_guard import (
    GuardRejection,
    guarded_fetch,
    ip_is_blocked,
    is_allowlisted_host,
    resolve_and_pin,
    sniff_image,
    validate_url,
)

# 1x1 PNG and a minimal JPEG/GIF/WEBP header for magic-byte tests.
PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64


def _no_dns(host, port):
    raise AssertionError(f"resolver must NOT run for {host}")


def _public_ip(host, port):
    return ["93.184.216.34"]


# ---------------------------------------------------------------------------
# Domain allow-list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host", [
    "nike.com", "images.nike.com", "www.nike.com",      # retailer + subdomains
    "asos.com", "cdn.shopify.com", "foo.shopifycdn.com",
    "d123.cloudfront.net", "media.scene7.com", "x.akamaized.net",
    "static.zara.net", "img.ztat.net", "bucket.s3.amazonaws.com",
])
def test_allowlisted_hosts(host):
    assert is_allowlisted_host(host) is True


@pytest.mark.parametrize("host", [
    "evil.example.com", "attacker.com",
    "evilnike.com",            # suffix without a dot boundary must NOT match nike.com
    "nike.com.evil.com",       # allow-listed label in the middle must NOT match
    "cloudfront.net.evil.com",
    "169.254.169.254",         # bare IPs are never name-allow-listed
    "10.0.0.1", "localhost", "", "no-dot",
])
def test_non_allowlisted_hosts(host):
    assert is_allowlisted_host(host) is False


# ---------------------------------------------------------------------------
# validate_url: scheme + domain gate (no network)
# ---------------------------------------------------------------------------

def test_validate_url_https_allowlisted_ok():
    parsed, host, port = validate_url("https://images.nike.com/p/shoe.jpg?sku=1")
    assert host == "images.nike.com"
    assert port == 443


@pytest.mark.parametrize("url,reason", [
    ("http://images.nike.com/x.jpg", "scheme"),       # http refused
    ("ftp://images.nike.com/x.jpg", "scheme"),
    ("file:///etc/passwd", "scheme"),
    ("https://attacker.evil.com/x.jpg", "domain"),    # not allow-listed
    ("https://169.254.169.254/latest/meta-data/", "domain"),  # metadata literal IP
    ("https://10.0.0.5/x.jpg", "domain"),
])
def test_validate_url_rejections(url, reason):
    with pytest.raises(GuardRejection) as ei:
        validate_url(url)
    assert ei.value.reason == reason


# ---------------------------------------------------------------------------
# IP validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ip", [
    "10.0.0.1", "10.255.255.255",
    "172.16.0.1", "172.31.255.255",
    "192.168.0.1", "192.168.1.1",
    "127.0.0.1", "127.1.2.3",
    "169.254.0.1", "169.254.169.254",          # link-local incl. cloud metadata
    "0.0.0.0",                                  # unspecified
    "224.0.0.1",                                # multicast
    "::1",                                      # IPv6 loopback
    "fc00::1", "fd12:3456::1",                  # IPv6 ULA (fc00::/7)
    "fe80::1",                                  # IPv6 link-local
    "::ffff:10.0.0.1",                          # IPv4-mapped private
    "not-an-ip",                                # unparseable -> blocked
])
def test_ip_is_blocked_true(ip):
    assert ip_is_blocked(ip) is True


@pytest.mark.parametrize("ip", [
    "1.1.1.1", "8.8.8.8", "93.184.216.34", "23.45.67.89",
    "2606:2800:220:1:248:1893:25c8:1946",       # public IPv6 (example.com)
])
def test_ip_is_blocked_false(ip):
    assert ip_is_blocked(ip) is False


def test_resolve_and_pin_blocks_mixed_records():
    """A name resolving to BOTH a public and a private address is hostile -> refuse."""
    with pytest.raises(GuardRejection) as ei:
        resolve_and_pin("images.nike.com", 443, lambda h, p: ["93.184.216.34", "10.0.0.1"])
    assert ei.value.reason == "private_ip"


def test_resolve_and_pin_returns_first_public():
    ip = resolve_and_pin("images.nike.com", 443, lambda h, p: ["93.184.216.34", "23.45.67.89"])
    assert ip == "93.184.216.34"


# ---------------------------------------------------------------------------
# Magic-byte sniffing — never trusts Content-Type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("data,suffix", [
    (PNG, ".png"), (JPEG, ".jpg"), (GIF, ".gif"), (WEBP, ".webp"),
])
def test_sniff_image_known(data, suffix):
    out = sniff_image(data)
    assert out is not None and out[0] == suffix


@pytest.mark.parametrize("data", [
    b"<html><body>not an image</body></html>" + b"\x00" * 20,
    b"GIF",                       # too short
    b"\x00" * 64,                 # no magic
])
def test_sniff_image_rejects_non_image(data):
    assert sniff_image(data) is None


# ---------------------------------------------------------------------------
# guarded_fetch — the two headline rejections (NO network reached)
# ---------------------------------------------------------------------------

def test_reject_non_allowlisted_domain():
    """(a) A URL on a non-allow-listed domain is refused before any DNS/packet."""
    client = httpx.Client()
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(client, "https://attacker.evil.com/x.jpg", resolver=_no_dns)
        assert ei.value.reason == "domain"
    finally:
        client.close()


def test_reject_private_ip_rebind():
    """(b) An allow-listed host that resolves to a private IP is refused (rebinding)."""
    client = httpx.Client()
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(
                client, "https://images.nike.com/p.jpg",
                resolver=lambda h, p: ["10.0.0.5"],
            )
        assert ei.value.reason == "private_ip"
    finally:
        client.close()


def test_reject_metadata_ip():
    """(b') The cloud metadata IP via an allow-listed host name is refused."""
    client = httpx.Client()
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(
                client, "https://images.nike.com/p.jpg",
                resolver=lambda h, p: ["169.254.169.254"],
            )
        assert ei.value.reason == "private_ip"
    finally:
        client.close()


def test_reject_http_scheme():
    client = httpx.Client()
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(client, "http://images.nike.com/p.jpg", resolver=_no_dns)
        assert ei.value.reason == "scheme"
    finally:
        client.close()


# ---------------------------------------------------------------------------
# guarded_fetch — behavioral paths via a MockTransport (pinned IP, no real net)
# ---------------------------------------------------------------------------

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_image_success_sniffs_png():
    def handler(request):
        # The connection is pinned to the IP; the real host rides in the Host header.
        assert request.headers["host"] == "images.nike.com"
        assert request.url.host == "93.184.216.34"
        return httpx.Response(200, content=PNG, headers={"content-type": "text/plain"})

    client = _client(handler)
    try:
        res = guarded_fetch(client, "https://images.nike.com/p.png", resolver=_public_ip)
        assert res.suffix == ".png" and res.content_type == "image/png"
        assert res.final_host == "images.nike.com"
    finally:
        client.close()


def test_fetch_image_non_image_body_rejected():
    def handler(request):
        return httpx.Response(200, content=b"<html>nope</html>" + b"\x00" * 20,
                              headers={"content-type": "image/png"})

    client = _client(handler)
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(client, "https://images.nike.com/p.png", resolver=_public_ip)
        assert ei.value.reason == "not_image"
    finally:
        client.close()


def test_redirect_to_non_allowlisted_is_revalidated():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://attacker.evil.com/x.png"})

    client = _client(handler)
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(client, "https://images.nike.com/p.png", resolver=_public_ip)
        assert ei.value.reason == "domain"   # the redirect target fails the allow-list
    finally:
        client.close()


def test_redirect_cap_exhausted():
    def handler(request):
        # Always bounce to another allow-listed host -> exhausts the redirect budget.
        return httpx.Response(302, headers={"location": "https://cdn.shopify.com/next.png"})

    client = _client(handler)
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(client, "https://images.nike.com/p.png", resolver=_public_ip)
        assert ei.value.reason == "redirects"
    finally:
        client.close()


def test_non_200_status_rejected():
    def handler(request):
        return httpx.Response(404, content=b"missing")

    client = _client(handler)
    try:
        with pytest.raises(GuardRejection) as ei:
            guarded_fetch(client, "https://images.nike.com/p.png", resolver=_public_ip)
        assert ei.value.reason == "http_status"
    finally:
        client.close()
