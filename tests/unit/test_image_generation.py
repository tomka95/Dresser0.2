"""Unit tests for the image-GENERATION provider seam (offline — no real APIs).

Providers talk to httpx.MockTransport clients (via each module's _client()
factory) or a stubbed genai client (via nano_banana._get_client), so no network
is ever touched. Covered: dispatch (enabled/unknown/missing-key/explicit-name),
GenerationBudget, the shared prompt's preserve/no-add invariants, each
provider's happy path, and the never-raise failure contract (moderation,
timeout, network error, non-image bytes, oversize responses, host allowlists).
"""
import base64
from types import SimpleNamespace

import httpx

import app.services.image_generation.flux_kontext as flux_module
import app.services.image_generation.nano_banana as nano_module
import app.services.image_generation.seedream as seedream_module
from app.core.config import settings
from app.services.image_generation import (
    MAX_GENERATED_BYTES,
    GenerationBudget,
    GenerationRequest,
    GenerationResult,
    NullGenerationProvider,
    build_generation_prompt,
    build_nano_generation_prompt,
    get_generation_provider,
    list_available_providers,
)
from app.services.image_generation.flux_kontext import FluxKontextProvider
from app.services.image_generation.nano_banana import NanoBananaProvider
from app.services.image_generation.seedream import SeedreamProvider

# Real magic bytes (the sniffer only inspects the leading bytes).
JPEG = b"\xff\xd8\xff" + b"fake-jpeg-body"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
NOT_AN_IMAGE = b"<html>definitely not an image</html>"

REQ = GenerationRequest(
    image_bytes=PNG,
    content_type="image/png",
    name="EZwear Halter Top",
    category="top",
    color="black",
    pattern="striped",
    brand="SHEIN",
)


def _configure(monkeypatch, **overrides):
    """Point settings at a fully-configured generation seam, then override."""
    values = dict(
        GENERATION_ENABLED=True,
        GENERATION_PROVIDER="flux_kontext",
        BFL_API_KEY="bfl-test-key",
        FAL_API_KEY="fal-test-key",
        GEMINI_API_KEY="gemini-test-key",
        GENERATION_TIMEOUT_SECONDS=5.0,
    )
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def test_dispatch_disabled_returns_null(monkeypatch):
    """Shipped state: GENERATION_ENABLED=False + no explicit name -> Null."""
    _configure(monkeypatch, GENERATION_ENABLED=False)
    assert isinstance(get_generation_provider(), NullGenerationProvider)


def test_dispatch_env_selects_default_provider(monkeypatch):
    _configure(monkeypatch)
    provider = get_generation_provider()
    assert isinstance(provider, FluxKontextProvider)
    assert provider.name == "flux_kontext"


def test_dispatch_env_selects_each_provider(monkeypatch):
    _configure(monkeypatch, GENERATION_PROVIDER="seedream")
    assert isinstance(get_generation_provider(), SeedreamProvider)
    _configure(monkeypatch, GENERATION_PROVIDER="nano_banana")
    assert isinstance(get_generation_provider(), NanoBananaProvider)


def test_dispatch_unknown_provider_returns_null(monkeypatch):
    _configure(monkeypatch, GENERATION_PROVIDER="dall-e-9000")
    assert isinstance(get_generation_provider(), NullGenerationProvider)


def test_dispatch_missing_key_returns_null(monkeypatch):
    _configure(monkeypatch, GENERATION_PROVIDER="seedream", FAL_API_KEY=None)
    assert isinstance(get_generation_provider(), NullGenerationProvider)
    _configure(monkeypatch, BFL_API_KEY=None)  # default flux without its key
    assert isinstance(get_generation_provider(), NullGenerationProvider)


def test_dispatch_explicit_name_overrides_env_and_flag(monkeypatch):
    """The bake-off passes names explicitly — works even while disabled."""
    _configure(monkeypatch, GENERATION_ENABLED=False, GENERATION_PROVIDER="flux_kontext")
    assert isinstance(get_generation_provider("seedream"), SeedreamProvider)
    assert isinstance(get_generation_provider("NANO_BANANA"), NanoBananaProvider)


def test_list_available_providers_reflects_keys(monkeypatch):
    _configure(monkeypatch, FAL_API_KEY=None)
    assert list_available_providers() == {
        "flux_kontext": True,
        "seedream": False,
        "nano_banana": True,
    }


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def test_budget_take_and_exhaust():
    budget = GenerationBudget(2)
    assert budget.remaining == 2
    assert budget.take() is True
    assert budget.take() is True
    assert budget.take() is False  # exhausted
    assert budget.remaining == 0


def test_budget_never_negative():
    budget = GenerationBudget(-3)
    assert budget.remaining == 0
    assert budget.take() is False


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def test_prompt_contains_invariants():
    prompt = build_generation_prompt(REQ)
    # ISOLATE: extract only the target garment, drop person/scene/other garments.
    assert "Extract ONLY the single target garment" in prompt
    assert "REMOVE the person" in prompt
    assert "Preserve the target garment EXACTLY" in prompt
    assert "Do NOT add any logo, text, brand mark" in prompt
    assert "No person, no mannequin" in prompt


def test_prompt_appends_attribute_hints():
    # category/color/pattern build the descriptor; name disambiguates the garment.
    assert build_generation_prompt(REQ).endswith(
        'The target garment is the black striped top ("EZwear Halter Top").'
    )


def test_prompt_includes_name_excludes_brand():
    """Name is included to pick WHICH garment; brand stays out (logo-paint risk)."""
    prompt = build_generation_prompt(REQ)
    assert "EZwear Halter Top" in prompt   # name conditions the isolation
    assert "SHEIN" not in prompt           # brand never enters the prompt


def test_prompt_without_attributes_has_no_target_descriptor():
    bare = GenerationRequest(image_bytes=PNG, content_type="image/png")
    prompt = build_generation_prompt(bare)
    assert "The target garment is" not in prompt


def test_prompt_is_deterministic():
    assert build_generation_prompt(REQ) == build_generation_prompt(REQ)


def test_nano_prompt_adds_logo_guard_without_weakening_base():
    """nano's prompt = shared prompt + the anti-logo-hallucination guard (additive)."""
    base = build_generation_prompt(REQ)
    nano = build_nano_generation_prompt(REQ)
    # Base is preserved verbatim as the prefix — no invariant relaxed.
    assert nano.startswith(base)
    assert "Extract ONLY the single target garment" in nano
    assert "REMOVE the person" in nano
    assert "No person, no mannequin" in nano
    # The added guard forbids adding / duplicating / relocating / inventing marks.
    assert "LOGOS, TEXT AND BRAND MARKS" in nano
    for verb in ("add", "invent", "duplicate", "mirror", "relocate"):
        assert verb in nano
    assert "leave it completely plain" in nano
    assert build_nano_generation_prompt(REQ) == nano  # deterministic


def test_nano_guard_is_provider_specific():
    """flux / seedream keep the shared prompt — the guard is nano-only."""
    assert "LOGOS, TEXT AND BRAND MARKS" not in build_generation_prompt(REQ)


# ---------------------------------------------------------------------------
# FLUX Kontext (submit -> poll -> signed-URL download)
# ---------------------------------------------------------------------------

_FLUX_POLL_URL = "https://api.bfl.ai/v1/get_result"
_FLUX_SAMPLE_URL = "https://delivery-us1.bfl.ai/results/sample.jpeg"


def _flux_transport(poll_payloads, *, sample_bytes=JPEG, sample_url=_FLUX_SAMPLE_URL):
    """MockTransport for the 3-step BFL flow. poll_payloads is consumed in order
    (the last one repeats — a stuck 'Pending' simulates a poll timeout)."""
    state = {"polls": 0}

    def handler(request):
        if request.method == "POST" and request.url.host == "api.bfl.ai":
            return httpx.Response(200, json={"id": "req-1", "polling_url": _FLUX_POLL_URL})
        if request.method == "GET" and request.url.path == "/v1/get_result":
            payload = poll_payloads[min(state["polls"], len(poll_payloads) - 1)]
            state["polls"] += 1
            if payload.get("status") == "Ready":
                payload = {**payload, "result": {"sample": sample_url}}
            return httpx.Response(200, json=payload)
        if request.method == "GET" and str(request.url) == sample_url:
            return httpx.Response(200, content=sample_bytes)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _use_flux_transport(monkeypatch, transport):
    monkeypatch.setattr(flux_module, "_client", lambda: httpx.Client(transport=transport))
    monkeypatch.setattr(flux_module, "_POLL_INTERVAL_S", 0.0)


def test_flux_happy_path(monkeypatch):
    _configure(monkeypatch)
    _use_flux_transport(
        monkeypatch, _flux_transport([{"status": "Pending"}, {"status": "Ready"}])
    )
    result = FluxKontextProvider().generate(REQ)
    assert isinstance(result, GenerationResult)
    assert result.image_bytes == JPEG
    assert result.content_type == "image/jpeg"  # from the sniff, not the API
    assert result.provider == "flux_kontext"
    assert result.model == "flux-kontext-pro"
    assert result.cost_usd == settings.FLUX_KONTEXT_USD_PER_IMAGE
    assert result.latency_s >= 0.0


def test_flux_moderation_returns_none(monkeypatch):
    _configure(monkeypatch)
    for status in ("Content Moderated", "Request Moderated", "Error"):
        _use_flux_transport(monkeypatch, _flux_transport([{"status": status}]))
        assert FluxKontextProvider().generate(REQ) is None


def test_flux_poll_timeout_returns_none(monkeypatch):
    _configure(monkeypatch, GENERATION_TIMEOUT_SECONDS=0.15)
    _use_flux_transport(monkeypatch, _flux_transport([{"status": "Pending"}]))
    monkeypatch.setattr(flux_module, "_POLL_INTERVAL_S", 0.01)
    assert FluxKontextProvider().generate(REQ) is None


def test_flux_network_error_returns_none(monkeypatch):
    _configure(monkeypatch)

    def boom(request):
        raise httpx.ConnectError("connection refused", request=request)

    _use_flux_transport(monkeypatch, httpx.MockTransport(boom))
    assert FluxKontextProvider().generate(REQ) is None


def test_flux_http_error_returns_none(monkeypatch):
    _configure(monkeypatch)
    _use_flux_transport(
        monkeypatch, httpx.MockTransport(lambda request: httpx.Response(500))
    )
    assert FluxKontextProvider().generate(REQ) is None


def test_flux_bad_bytes_returns_none(monkeypatch):
    """Delivery URL serving non-image bytes fails the sniff -> None."""
    _configure(monkeypatch)
    _use_flux_transport(
        monkeypatch,
        _flux_transport([{"status": "Ready"}], sample_bytes=NOT_AN_IMAGE),
    )
    assert FluxKontextProvider().generate(REQ) is None


def test_flux_oversize_returns_none(monkeypatch):
    _configure(monkeypatch)
    huge = b"\xff\xd8\xff" + b"\x00" * MAX_GENERATED_BYTES  # real magic, over cap
    _use_flux_transport(
        monkeypatch, _flux_transport([{"status": "Ready"}], sample_bytes=huge)
    )
    assert FluxKontextProvider().generate(REQ) is None


def test_flux_off_family_delivery_host_returns_none(monkeypatch):
    """Signed URL outside the bfl.ai family must never be fetched."""
    _configure(monkeypatch)
    _use_flux_transport(
        monkeypatch,
        _flux_transport(
            [{"status": "Ready"}], sample_url="https://evil.example.com/sample.jpeg"
        ),
    )
    assert FluxKontextProvider().generate(REQ) is None


def test_flux_missing_key_returns_none(monkeypatch):
    _configure(monkeypatch, BFL_API_KEY=None)
    assert FluxKontextProvider().generate(REQ) is None


# ---------------------------------------------------------------------------
# Seedream (single synchronous POST; result URL or data URI)
# ---------------------------------------------------------------------------

_SEEDREAM_RESULT_URL = "https://v3.fal.media/files/output.png"


def _seedream_transport(result_url, *, result_bytes=PNG):
    def handler(request):
        if request.method == "POST" and request.url.host == "fal.run":
            return httpx.Response(200, json={"images": [{"url": result_url}], "seed": 7})
        if request.method == "GET" and str(request.url) == result_url:
            return httpx.Response(200, content=result_bytes)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _use_seedream_transport(monkeypatch, transport):
    monkeypatch.setattr(
        seedream_module, "_client", lambda: httpx.Client(transport=transport)
    )


def test_seedream_happy_path_url(monkeypatch):
    _configure(monkeypatch)
    _use_seedream_transport(monkeypatch, _seedream_transport(_SEEDREAM_RESULT_URL))
    result = SeedreamProvider().generate(REQ)
    assert isinstance(result, GenerationResult)
    assert result.image_bytes == PNG
    assert result.content_type == "image/png"
    assert result.provider == "seedream"
    assert result.cost_usd == settings.SEEDREAM_USD_PER_IMAGE


def test_seedream_happy_path_data_uri(monkeypatch):
    """A data-URI result is decoded locally — no download round-trip at all."""
    _configure(monkeypatch)
    data_uri = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode("ascii")
    _use_seedream_transport(monkeypatch, _seedream_transport(data_uri))
    result = SeedreamProvider().generate(REQ)
    assert result is not None
    assert result.image_bytes == JPEG
    assert result.content_type == "image/jpeg"


def test_seedream_off_family_result_host_returns_none(monkeypatch):
    _configure(monkeypatch)
    _use_seedream_transport(
        monkeypatch, _seedream_transport("https://evil.example.com/output.png")
    )
    assert SeedreamProvider().generate(REQ) is None


def test_seedream_network_error_returns_none(monkeypatch):
    _configure(monkeypatch)

    def boom(request):
        raise httpx.ConnectError("connection refused", request=request)

    _use_seedream_transport(monkeypatch, httpx.MockTransport(boom))
    assert SeedreamProvider().generate(REQ) is None


def test_seedream_bad_bytes_returns_none(monkeypatch):
    _configure(monkeypatch)
    _use_seedream_transport(
        monkeypatch,
        _seedream_transport(_SEEDREAM_RESULT_URL, result_bytes=NOT_AN_IMAGE),
    )
    assert SeedreamProvider().generate(REQ) is None


def test_seedream_oversize_returns_none(monkeypatch):
    _configure(monkeypatch)
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_GENERATED_BYTES
    _use_seedream_transport(
        monkeypatch, _seedream_transport(_SEEDREAM_RESULT_URL, result_bytes=huge)
    )
    assert SeedreamProvider().generate(REQ) is None


def test_seedream_empty_images_returns_none(monkeypatch):
    _configure(monkeypatch)

    def handler(request):
        return httpx.Response(200, json={"images": []})

    _use_seedream_transport(monkeypatch, httpx.MockTransport(handler))
    assert SeedreamProvider().generate(REQ) is None


def test_seedream_balance_403_sets_sticky_account_skip(monkeypatch):
    """fal 403 'exhausted balance' is an ACCOUNT skip, not a gen failure: the
    provider records unavailable_reason and short-circuits later calls."""
    _configure(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            403,
            json={"detail": "User is locked. Reason: Exhausted balance. "
                            "Top up your balance at fal.ai/dashboard/billing."},
        )

    _use_seedream_transport(monkeypatch, httpx.MockTransport(handler))
    provider = SeedreamProvider()
    assert provider.unavailable_reason is None
    assert provider.generate(REQ) is None
    assert provider.unavailable_reason == "no balance — top up at fal.ai/dashboard/billing"
    # Second call must NOT hit fal again (sticky short-circuit).
    assert provider.generate(REQ) is None
    assert calls["n"] == 1


def test_seedream_non_balance_4xx_is_plain_failure(monkeypatch):
    """A non-account 4xx (e.g. 422 bad request) is a normal generation failure —
    it must NOT set unavailable_reason (would mis-bucket as a skip)."""
    _configure(monkeypatch)

    def handler(request):
        return httpx.Response(422, json={"detail": "validation error"})

    _use_seedream_transport(monkeypatch, httpx.MockTransport(handler))
    provider = SeedreamProvider()
    assert provider.generate(REQ) is None
    assert provider.unavailable_reason is None


def test_seedream_is_account_locked_predicate():
    assert seedream_module._is_account_locked(403, '{"detail": "Exhausted balance."}')
    assert seedream_module._is_account_locked(403, "User is locked.")
    assert not seedream_module._is_account_locked(422, "Exhausted balance.")
    assert not seedream_module._is_account_locked(403, "moderation triggered")


def test_seedream_missing_key_returns_none(monkeypatch):
    _configure(monkeypatch, FAL_API_KEY=None)
    assert SeedreamProvider().generate(REQ) is None


# ---------------------------------------------------------------------------
# Nano Banana (Gemini inline_data in -> inline_data image part out)
# ---------------------------------------------------------------------------

def _genai_response(parts):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))]
    )


def _image_part(data):
    return SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type="image/jpeg"))


class _FakeGenaiClient:
    def __init__(self, response=None, exc=None):
        self.calls = []
        self._response = response
        self._exc = exc
        self.models = SimpleNamespace(generate_content=self._generate_content)

    def _generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._exc is not None:
            raise self._exc
        return self._response


def _use_genai(monkeypatch, fake):
    monkeypatch.setattr(nano_module, "_get_client", lambda: fake)


def test_nano_banana_happy_path(monkeypatch):
    _configure(monkeypatch)
    fake = _FakeGenaiClient(response=_genai_response([_image_part(JPEG)]))
    _use_genai(monkeypatch, fake)
    result = NanoBananaProvider().generate(REQ)
    assert isinstance(result, GenerationResult)
    assert result.image_bytes == JPEG
    assert result.content_type == "image/jpeg"
    assert result.provider == "nano_banana"
    assert result.model == settings.NANO_BANANA_MODEL
    assert result.cost_usd == settings.NANO_BANANA_USD_PER_IMAGE
    # The call sent the cutout inline + the shared prompt to the pinned model.
    call = fake.calls[0]
    assert call["model"] == settings.NANO_BANANA_MODEL
    assert call["contents"][0]["inline_data"]["data"] == REQ.image_bytes
    # …and the text part carries the nano-specific anti-logo-hallucination guard.
    assert call["contents"][1]["text"] == build_nano_generation_prompt(REQ)
    assert "LOGOS, TEXT AND BRAND MARKS" in call["contents"][1]["text"]


def test_nano_banana_base64_string_data(monkeypatch):
    """The SDK sometimes hands inline_data.data back as a base64 STRING."""
    _configure(monkeypatch)
    encoded = base64.b64encode(JPEG).decode("ascii")
    fake = _FakeGenaiClient(response=_genai_response([_image_part(encoded)]))
    _use_genai(monkeypatch, fake)
    result = NanoBananaProvider().generate(REQ)
    assert result is not None
    assert result.image_bytes == JPEG


def test_nano_banana_sdk_error_returns_none(monkeypatch):
    _configure(monkeypatch)
    _use_genai(monkeypatch, _FakeGenaiClient(exc=RuntimeError("api exploded")))
    assert NanoBananaProvider().generate(REQ) is None


def test_nano_banana_no_image_part_returns_none(monkeypatch):
    _configure(monkeypatch)
    text_only = _genai_response([SimpleNamespace(inline_data=None, text="no can do")])
    _use_genai(monkeypatch, _FakeGenaiClient(response=text_only))
    assert NanoBananaProvider().generate(REQ) is None


def test_nano_banana_bad_bytes_returns_none(monkeypatch):
    _configure(monkeypatch)
    fake = _FakeGenaiClient(response=_genai_response([_image_part(NOT_AN_IMAGE)]))
    _use_genai(monkeypatch, fake)
    assert NanoBananaProvider().generate(REQ) is None


def test_nano_banana_oversize_returns_none(monkeypatch):
    _configure(monkeypatch)
    huge = b"\xff\xd8\xff" + b"\x00" * MAX_GENERATED_BYTES
    fake = _FakeGenaiClient(response=_genai_response([_image_part(huge)]))
    _use_genai(monkeypatch, fake)
    assert NanoBananaProvider().generate(REQ) is None


def test_nano_banana_missing_key_returns_none(monkeypatch):
    _configure(monkeypatch, GEMINI_API_KEY=None)
    assert NanoBananaProvider().generate(REQ) is None
