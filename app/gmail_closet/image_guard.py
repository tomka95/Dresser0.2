"""SSRF-hardened outbound fetch guard for email-embedded image resolution.

THREAT MODEL
------------
The receipt HTML we parse is attacker-controllable: a crafted email can point an
``<img src>`` or product ``<a href>`` at an internal address (``http://10.0.0.5``,
``http://169.254.169.254/latest/meta-data/`` ...) hoping we will fetch it from
inside the network. EVERY outbound fetch triggered by email content MUST go through
``guarded_fetch`` here. This module is deliberately self-contained and
dependency-light so it can be unit-tested in isolation (see
tests/unit/test_image_guard.py).

THE GUARDS (all mandatory, applied on the initial URL AND on every redirect hop):
  1. Scheme allow-list: ``https`` only. No http / file:// / data:// / ftp ...
  2. Domain allow-list: the host's registrable domain must be a known retailer
     (retailers.RETAILER_DOMAINS) OR a known retail-image CDN (_CDN_SUFFIXES).
     Anything else is REFUSED before a single packet leaves the process.
  3. DNS + IP validation: resolve the host, and REFUSE if ANY resolved address is
     private / loopback / link-local / ULA / unspecified / multicast / reserved or
     the cloud-metadata IP (169.254.169.254). Then PIN the connection to the
     validated IP and force TLS SNI/cert-validation to the original hostname — we
     connect by IP, never re-resolve the hostname, which closes the DNS-rebinding
     window (resolve-public-then-swap-to-private).
  4. Redirect cap (<= MAX_REDIRECTS) with FULL re-validation (scheme + domain +
     DNS/IP) of every hop. A redirect to a non-allow-listed / private target is
     refused, not followed.
  5. Timeout + max-size caps. The body is streamed and aborted past the cap.
  6. Content sniffing: an image response is verified by MAGIC BYTES, never by the
     Content-Type header (which the attacker also controls).

REDACTION: never log a full URL (it may carry query-string secrets/tokens). Log
the host and a machine reason code only.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import httpx

from app.gmail_closet.retailers import RETAILER_DOMAINS

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

FETCH_TIMEOUT = 5.0          # seconds, per hop
MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 MB
MAX_HTML_BYTES = 2 * 1024 * 1024    # 2 MB (product page, og:image lookup only)
MAX_REDIRECTS = 2

# Known retail IMAGE/asset CDNs. A host is allow-listed if its registrable domain
# is a retailer (RETAILER_DOMAINS, incl. subdomains like images.nike.com) OR the
# host falls under one of these CDN suffixes. These all resolve to PUBLIC IPs in
# practice; the IP guard (step 3) is still applied, so even an allow-listed host
# that resolves to a private address is refused. Kept conservative and extendable.
_CDN_SUFFIXES: Tuple[str, ...] = (
    # Shopify (huge share of DTC brands)
    "cdn.shopify.com", "shopifycdn.com", "shopifycdn.net",
    # Generic big CDNs retailers serve product imagery from
    "cloudfront.net", "akamaized.net", "akamaihd.net", "akamai.net",
    "fastly.net", "fastlylb.net", "imgix.net", "cloudinary.com",
    # Adobe Scene7 / Salesforce Commerce (Demandware) dynamic media
    "scene7.com", "demandware.net", "dwcdn.net",
    # Object stores commonly fronting product images
    "amazonaws.com", "googleusercontent.com",
    # Headless-CMS image CDNs
    "ctfassets.net", "sanity.io",
    # Retailer-specific media CDNs
    "asos-media.com", "zara.net", "ztat.net", "nordstrommedia.com",
    "scal-fashion.com",
    # SHEIN's dedicated static/image CDN. SHEIN product images serve from
    # *.ltwebstatic.com (img / common / sheinsz / shein ...), NOT from shein.com —
    # so the allow-listed shein.com sender domain alone never matched the image
    # host and every SHEIN image was refused at the domain gate. This also covers
    # SHEIN-marketplace brands whose storefront is hosted on SHEIN (e.g. MUSERA,
    # which is a SHEIN store and serves its imagery from ltwebstatic.com too).
    "ltwebstatic.com",
    # Wix media CDN (static.wixstatic.com/media/...). A large share of long-tail
    # Israeli boutiques run their storefront on Wix and serve product imagery here.
    "wixstatic.com",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GuardRejection(Exception):
    """An outbound fetch was refused (or failed) by the SSRF guard.

    ``reason`` is a short machine code for telemetry/tests; ``host`` is safe to log
    (never the full URL). Reasons: 'scheme', 'domain', 'dns', 'private_ip',
    'redirects', 'redirect_no_location', 'http_status', 'too_large', 'not_image',
    'empty', 'network', 'fetch_budget'.
    """

    def __init__(self, reason: str, host: str = "", detail: str = ""):
        self.reason = reason
        self.host = host
        self.detail = detail
        super().__init__(f"{reason}" + (f" host={host}" if host else "") + (f" {detail}" if detail else ""))


class FetchBudget:
    """Per-run anti-amplification ceiling on outbound guarded fetches. Thread-safe.

    Shared across all items/candidates in a sync and across BOTH fetch profiles, so a
    crafted email or a fan-out of shopping-search candidates cannot turn one run into
    an unbounded number of outbound requests. take() consumes one unit per
    guarded_fetch call; when exhausted, guarded_fetch raises GuardRejection.
    """

    def __init__(self, limit: int):
        self._lock = threading.Lock()
        self._remaining = max(0, int(limit))

    def take(self) -> bool:
        with self._lock:
            if self._remaining <= 0:
                return False
            self._remaining -= 1
            return True

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._remaining


# A resolver maps (host, port) -> list of IP strings. Injectable so tests can
# simulate DNS (incl. a public host that "rebinds" to a private address) without
# real network access.
Resolver = Callable[[str, int], List[str]]


def _default_resolver(host: str, port: int) -> List[str]:
    """Resolve host -> all A/AAAA addresses via the OS resolver."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise GuardRejection("dns", host, type(exc).__name__)
    out: List[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and sockaddr[0]:
            out.append(sockaddr[0])
    if not out:
        raise GuardRejection("dns", host, "no addresses")
    return out


# ---------------------------------------------------------------------------
# Step 1+2: scheme + domain allow-list
# ---------------------------------------------------------------------------

def is_allowlisted_host(host: Optional[str]) -> bool:
    """True iff ``host`` is a known retailer domain (or subdomain) or retail CDN.

    Matching is suffix-anchored on a dot boundary so ``evilnike.com`` does NOT match
    ``nike.com`` and ``nike.com.evil.com`` does NOT match either — only ``nike.com``
    and ``*.nike.com`` do.
    """
    if not host:
        return False
    h = host.strip().lower().rstrip(".")
    if not h or "." not in h:
        return False
    for base in RETAILER_DOMAINS:
        if h == base or h.endswith("." + base):
            return True
    for cdn in _CDN_SUFFIXES:
        if h == cdn or h.endswith("." + cdn):
            return True
    return False


def _is_ip_literal(host: str) -> bool:
    """True if ``host`` is a bare IPv4/IPv6 address literal (IPv6 may be bracketed)."""
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def validate_url(url: str, *, profile: str = "retailer") -> Tuple[httpx.URL, str, int]:
    """Validate scheme + (retailer profile) domain. Returns (parsed_url, host, port).

    ``profile='retailer'`` (default): host's registrable domain must be allow-listed.
    ``profile='open'``: the ALLOW-LIST GATE IS SKIPPED (for non-allowlisted
    shopping-search hosts). EVERY OTHER GUARD IS UNCHANGED — https-only, bare-IP
    rejection here, and the downstream DNS-resolve + IP-pin + rebind defense + redirect
    re-validation + size/time caps + magic-byte sniff in guarded_fetch.

    No network is touched here — this is the cheap pre-DNS gate. Raises GuardRejection.
    """
    try:
        parsed = httpx.URL(url)
    except Exception as exc:
        raise GuardRejection("scheme", "", f"unparseable:{type(exc).__name__}")

    if parsed.scheme != "https":
        raise GuardRejection("scheme", parsed.host or "", f"scheme={parsed.scheme!r}")

    host = parsed.host
    if not host:
        raise GuardRejection("domain", "", "no host")

    # Reject bare-IP hosts in BOTH profiles: the resolve+pin+rebind model needs a
    # hostname, and an IP literal would otherwise let the open profile connect by raw
    # address. In the retailer profile this was previously enforced implicitly by the
    # name-based allow-list. Blocks ``https://169.254.169.254/`` and ``https://10.0.0.5/``.
    if _is_ip_literal(host):
        raise GuardRejection("domain", host, "bare ip")

    # Domain allow-list: enforced for retailer; SKIPPED only for the open profile.
    if profile != "open" and not is_allowlisted_host(host):
        raise GuardRejection("domain", host, "not allow-listed")

    port = parsed.port or 443
    return parsed, host, port


# ---------------------------------------------------------------------------
# Step 3: IP validation
# ---------------------------------------------------------------------------

def ip_is_blocked(ip_str: str) -> bool:
    """True if ``ip_str`` is an address we must NEVER connect to from email content.

    Blocks private (10/8, 172.16/12, 192.168/16), loopback (127/8, ::1), link-local
    (169.254/16 incl. the 169.254.169.254 metadata IP, fe80::/10), ULA (fc00::/7),
    unspecified, multicast and reserved ranges. IPv4-mapped IPv6 (::ffff:10.0.0.1)
    is unwrapped and checked as its IPv4 form so it cannot be used to smuggle a
    private target past the filter.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # un-parseable address -> refuse

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    ):
        return True

    # Explicit, belt-and-suspenders metadata guard (already covered by is_link_local
    # for IPv4, but called out so the intent is unmissable and IPv6 metadata variants
    # are covered too).
    if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
        return True

    return False


def resolve_and_pin(host: str, port: int, resolver: Resolver) -> str:
    """Resolve ``host`` and return ONE validated public IP to pin the connection to.

    REFUSES (raises) if ANY resolved address is blocked — a name that resolves to a
    mix of public and private addresses is treated as hostile (a classic rebinding
    setup), not "use the good one".
    """
    addrs = resolver(host, port)
    for ip in addrs:
        if ip_is_blocked(ip):
            raise GuardRejection("private_ip", host, "resolved to blocked address")
    return addrs[0]


# ---------------------------------------------------------------------------
# Step 6: image magic-byte sniffing
# ---------------------------------------------------------------------------

def sniff_image(data: bytes) -> Optional[Tuple[str, str]]:
    """Return (suffix, content_type) if ``data`` starts with known image magic bytes.

    Trusts the BYTES, never a Content-Type header. None => not a recognized image.
    """
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg", "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif", "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    # ISO-BMFF (AVIF / HEIC): a 'ftyp' box whose major brand is an image brand.
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis", b"heic", b"heif", b"mif1"):
        brand = data[8:12]
        return (".avif", "image/avif") if brand in (b"avif", b"avis") else (".heic", "image/heic")
    return None


# ---------------------------------------------------------------------------
# The guarded fetch
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    """A successful guarded fetch."""
    content: bytes
    content_type: str   # sniffed (image) or response header (html), best-effort
    suffix: str         # image suffix from magic bytes; '' for html
    final_host: str     # host of the last hop actually fetched


def _pinned_send(
    client: httpx.Client,
    parsed: httpx.URL,
    host: str,
    port: int,
    ip: str,
    *,
    timeout: float,
) -> httpx.Response:
    """Issue ONE GET pinned to ``ip`` with TLS validated against ``host``.

    The URL host is swapped for the literal IP so httpcore connects to the validated
    address and performs NO second DNS lookup. The Host header and TLS SNI/cert check
    are forced back to the real hostname via the header override + ``sni_hostname``
    request extension, so virtual-hosted CDNs route correctly and certificate
    validation is against the hostname (not the IP). follow_redirects is OFF — hops
    are handled (and re-validated) by the caller.
    """
    ip_literal = f"[{ip}]" if ":" in ip else ip
    pinned = parsed.copy_with(host=ip_literal, port=port)
    headers = {"Host": host if port == 443 else f"{host}:{port}",
               "Accept": "image/*,text/html;q=0.8,*/*;q=0.5",
               "User-Agent": "TailorClosetImageResolver/1.0"}
    request = client.build_request(
        "GET",
        pinned,
        headers=headers,
        timeout=httpx.Timeout(timeout),
        extensions={"sni_hostname": host},
    )
    return client.send(request, stream=True, follow_redirects=False)


def _read_capped(resp: httpx.Response, max_bytes: int, host: str) -> bytes:
    """Stream the body, aborting (raise) once it exceeds ``max_bytes``."""
    total = 0
    chunks: List[bytes] = []
    for chunk in resp.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise GuardRejection("too_large", host, f">{max_bytes}B")
        chunks.append(chunk)
    return b"".join(chunks)


def guarded_fetch(
    client: httpx.Client,
    url: str,
    *,
    kind: str = "image",            # 'image' | 'html'
    resolver: Resolver = _default_resolver,
    max_redirects: int = MAX_REDIRECTS,
    timeout: float = FETCH_TIMEOUT,
    profile: str = "retailer",      # 'retailer' (allow-listed) | 'open' (no allow-list)
    fetch_budget: Optional[FetchBudget] = None,
) -> FetchResult:
    """Fetch ``url`` through ALL SSRF guards, following <= max_redirects hops.

    ``kind='image'`` verifies magic bytes and caps at MAX_IMAGE_BYTES.
    ``kind='html'`` decodes text and caps at MAX_HTML_BYTES (used only to read
    og:image off a product page). ``profile`` selects the allow-list policy (see
    validate_url) — every OTHER guard is identical across profiles. ``fetch_budget``
    (per-run, shared) enforces the anti-amplification ceiling. Raises GuardRejection
    on any refusal/failure.
    """
    # Anti-amplification: one logical outbound fetch consumes one unit of the
    # per-run ceiling (checked BEFORE any DNS/connect, and before the redirect loop).
    if fetch_budget is not None and not fetch_budget.take():
        raise GuardRejection("fetch_budget", "", "per-run ceiling reached")

    max_bytes = MAX_IMAGE_BYTES if kind == "image" else MAX_HTML_BYTES
    current = url

    for _hop in range(max_redirects + 1):
        # (1) scheme + (2) domain (per profile) — re-validated on every hop.
        parsed, host, port = validate_url(current, profile=profile)
        # (3) DNS + IP — re-resolved and re-validated on every hop, then pinned.
        ip = resolve_and_pin(host, port, resolver)

        try:
            resp = _pinned_send(client, parsed, host, port, ip, timeout=timeout)
        except GuardRejection:
            raise
        except (httpx.HTTPError, OSError) as exc:
            # ssl.SSLError subclasses OSError, so TLS failures land here too.
            raise GuardRejection("network", host, type(exc).__name__)

        try:
            status = resp.status_code
            # (4) redirects — capped + re-validated by looping with the new URL.
            if 300 <= status < 400:
                location = resp.headers.get("location")
                if not location:
                    raise GuardRejection("redirect_no_location", host)
                current = str(httpx.URL(parsed).join(location))
                continue

            if status != 200:
                raise GuardRejection("http_status", host, str(status))

            # (5) size cap while streaming.
            body = _read_capped(resp, max_bytes, host)
        finally:
            resp.close()

        if not body:
            raise GuardRejection("empty", host)

        if kind == "image":
            # (6) magic-byte verification — Content-Type header is NOT trusted.
            sniff = sniff_image(body)
            if sniff is None:
                raise GuardRejection("not_image", host)
            suffix, ctype = sniff
            return FetchResult(content=body, content_type=ctype, suffix=suffix, final_host=host)

        # html: best-effort content type from header (text only, not security-bearing).
        ctype = (resp.headers.get("content-type") or "text/html").split(";")[0].strip()
        return FetchResult(content=body, content_type=ctype, suffix="", final_host=host)

    raise GuardRejection("redirects", "", f">{max_redirects}")
