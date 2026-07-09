"""FLUX.2 [pro] BFL provider (rung-1): submit->poll->fetch, reference-image mapping,
SSRF allowlist, and the safe-fail contract. No network — httpx is faked.

These lock the facts the cost/quality change depends on: FLUX.2 hits the flux-2-pro
endpoint, conditions on the garment cutout as the base64 `input_image` reference (so the
on-model routing + Regenerate ref path actually work), prices at FLUX2_PRO_USD_PER_IMAGE,
and returns None (never raises, never leaks) on any failure so the ladder falls to nano.
"""
from __future__ import annotations

import base64

import pytest

from app.core.config import settings
from app.services.image_generation import flux2_pro as f2
from app.services.image_generation.base import GenerationRequest


class _Resp:
    def __init__(self, payload=None, content=None):
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Scriptable httpx.Client stand-in: records the submit body, scripts poll+fetch."""

    def __init__(self, *, poll_status="Ready", sample_url="https://delivery-us1.bfl.ai/x.jpg",
                 polling_url="https://api.bfl.ai/v1/poll/abc"):
        self.poll_status = poll_status
        self.sample_url = sample_url
        self.polling_url = polling_url
        self.submitted_json = None
        self.fetched_urls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self.submitted_json = json
        assert url == f2._SUBMIT_URL
        return _Resp(payload={"id": "req-1", "polling_url": self.polling_url})

    def get(self, url, headers=None, params=None):
        if url == self.polling_url:
            return _Resp(payload={"status": self.poll_status,
                                  "result": {"sample": self.sample_url}})
        # delivery fetch
        self.fetched_urls.append(url)
        return _Resp(content=b"\xff\xd8\xffimg-bytes")


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(settings, "BFL_API_KEY", "bfl-test-key")
    # Isolate from the real magic-byte sniffer — a valid image is assumed here.
    monkeypatch.setattr(f2, "sniff_generated_image", lambda data: "image/jpeg")


def _req(ref=b"garment-cutout-bytes"):
    return GenerationRequest(
        image_bytes=ref, content_type="image/png",
        name="Blue Tee", category="top", color="blue", brand="Acme",
    )


def test_flux2_conditions_on_reference_and_prices(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(f2, "_client", lambda: fake)

    result = f2.Flux2ProProvider().generate(_req(b"REF-BYTES"))

    assert result is not None
    assert result.provider == "flux2_pro" and result.model == "flux-2-pro"
    assert result.cost_usd == pytest.approx(settings.FLUX2_PRO_USD_PER_IMAGE)
    assert result.content_type == "image/jpeg"
    # Reference-image conditioning: the cutout is sent as the base64 `input_image`.
    body = fake.submitted_json
    assert base64.b64decode(body["input_image"]) == b"REF-BYTES"
    assert body["prompt"]                      # a real prompt was built
    assert body["output_format"] == "jpeg"


def test_flux2_missing_key_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "BFL_API_KEY", None)
    # Never even builds a client when unconfigured.
    monkeypatch.setattr(f2, "_client", lambda: pytest.fail("must not call BFL without a key"))
    assert f2.Flux2ProProvider().generate(_req()) is None


def test_flux2_terminal_failure_returns_none(monkeypatch):
    fake = _FakeClient(poll_status="Content Moderated")
    monkeypatch.setattr(f2, "_client", lambda: fake)
    assert f2.Flux2ProProvider().generate(_req()) is None
    assert fake.fetched_urls == []             # never fetched a sample on a moderated miss


def test_flux2_rejects_non_bfl_delivery_host(monkeypatch):
    # SSRF allowlist: a delivery URL off the bfl.ai family is dropped -> None (never fetched).
    fake = _FakeClient(sample_url="https://evil.example.com/x.jpg")
    monkeypatch.setattr(f2, "_client", lambda: fake)
    assert f2.Flux2ProProvider().generate(_req()) is None
    assert fake.fetched_urls == []


def test_flux2_rejects_non_bfl_polling_host(monkeypatch):
    fake = _FakeClient(polling_url="https://evil.example.com/poll")
    monkeypatch.setattr(f2, "_client", lambda: fake)
    assert f2.Flux2ProProvider().generate(_req()) is None
