"""Wave 1 photo detection: schema parsing, person_count, and failure-soft behavior.

No real Gemini call — a fake provider stands in for AIProvider.generate_structured.
"""
from __future__ import annotations

import json

from app.photo_closet.detection import (
    DetectionResult,
    GarmentCategory,
    detect_garments_with_regions,
)


class _FakeResp:
    def __init__(self, parsed=None, text=None):
        self.parsed = parsed
        self.text = text


class _FakeProvider:
    def __init__(self, resp=None, raises=False):
        self._resp = resp
        self._raises = raises
        self.calls = []

    def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("boom")
        return self._resp


def test_parses_parsed_instance():
    parsed = DetectionResult(
        person_count=1,
        garments=[
            {"name": "Blue Tee", "category": "top", "color": "blue",
             "box_2d": [100, 120, 480, 560], "confidence_overall": 0.9},
        ],
    )
    prov = _FakeProvider(_FakeResp(parsed=parsed))
    out = detect_garments_with_regions(
        image_bytes=b"x", content_type="image/jpeg", provider=prov)
    assert out.person_count == 1
    assert len(out.garments) == 1
    g = out.garments[0]
    assert g.category == GarmentCategory.top
    assert g.box_2d == [100, 120, 480, 560]
    # The detector targeted the configured detect model.
    assert "model" in prov.calls[0]


def test_parses_raw_json_text():
    payload = {
        "person_count": 0,
        "garments": [
            {"name": "Chinos", "category": "bottom", "box_2d": [10, 20, 30, 40]},
        ],
    }
    prov = _FakeProvider(_FakeResp(text=json.dumps(payload)))
    out = detect_garments_with_regions(
        image_bytes=b"x", content_type="image/png", provider=prov)
    assert out.person_count == 0
    assert out.garments[0].category == GarmentCategory.bottom


def test_unknown_category_falls_back_to_other():
    payload = {"person_count": 1, "garments": [
        {"name": "Mystery", "category": "spacesuit", "box_2d": [0, 0, 1, 1]}]}
    # Pydantic rejects the bad enum at the garment level; the whole parse fails ->
    # failure-soft empty result (we never 500 on a bad model payload).
    prov = _FakeProvider(_FakeResp(text=json.dumps(payload)))
    out = detect_garments_with_regions(
        image_bytes=b"x", content_type="image/png", provider=prov)
    assert out.garments == []


def test_provider_error_is_soft():
    prov = _FakeProvider(raises=True)
    out = detect_garments_with_regions(
        image_bytes=b"x", content_type="image/jpeg", provider=prov)
    assert out.person_count == 0 and out.garments == []


def test_max_items_cap():
    garments = [
        {"name": f"g{i}", "category": "top", "box_2d": [0, 0, 1, 1]} for i in range(20)
    ]
    prov = _FakeProvider(_FakeResp(text=json.dumps({"person_count": 1, "garments": garments})))
    out = detect_garments_with_regions(
        image_bytes=b"x", content_type="image/jpeg", max_items=5, provider=prov)
    assert len(out.garments) == 5
