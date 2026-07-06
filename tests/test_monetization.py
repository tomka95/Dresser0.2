"""F1c: monetization — /clicks + /out redirect, wrap fallback chain, no user data out."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal, Base, engine
from app.models import Product, ProductClick, StyleEvent, User
from app.monetization import config as mon_config
from app.monetization.wrap import wrap_url
from app.security import create_access_token
from main import app


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user1(db: Session):
    u = User(email="m1@example.com", hashed_password="x", display_name="M1")
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def product(db: Session):
    p = Product(source="search", name="MUSERA Denim Jacket",
                canonical_url="https://retailer.example/p/denim-jacket-123",
                product_url="https://retailer.example/p/denim-jacket-123?utm=x",
                category="outerwear")
    db.add(p); db.commit(); db.refresh(p)
    return p


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _tok(user):
    return create_access_token(data={"sub": str(user.id)})


# ---------------------------------------------------------------------------
# Wrap resolver fallback chain
# ---------------------------------------------------------------------------
DEST = "https://retailer.example/p/denim-jacket-123"
CID = "11111111-1111-1111-1111-111111111111"


def test_wrap_plain_when_nothing_configured():
    r = wrap_url(DEST, CID)
    assert r.url == DEST and r.network is None and r.wrapped is False


def test_wrap_sovrn_when_configured(monkeypatch):
    monkeypatch.setattr(mon_config, "sovrn_site_id", lambda: "SOVRN123")
    r = wrap_url(DEST, CID)
    assert r.wrapped and r.network == "sovrn"
    assert "viglink.com" in r.url and f"cuid={CID}" in r.url


def test_wrap_skimlinks_when_configured(monkeypatch):
    monkeypatch.setattr(mon_config, "skimlinks_publisher_id", lambda: "SKIM99")
    r = wrap_url(DEST, CID)
    assert r.wrapped and r.network == "skimlinks" and "skimresources.com" in r.url


def test_wrap_direct_deeplink_takes_precedence(monkeypatch):
    monkeypatch.setattr(mon_config, "program_affiliate_ids", lambda: {"shein.com": "AFF1"})
    monkeypatch.setattr(mon_config, "sovrn_site_id", lambda: "SOVRN123")  # would win if no deeplink
    r = wrap_url("https://us.shein.com/p/dress-999.html", CID)
    assert r.network == "shein" and r.wrapped and f"subid={CID}" in r.url


def test_wrap_never_leaks_user_data():
    # The only dynamic parts of any wrapped URL are the dest URL + the opaque click_id.
    for fn in (lambda: None,):
        r = wrap_url(DEST, CID)
        assert "@" not in r.url.split("//", 1)[-1].split("/")[0]  # no email in host
        assert "user" not in r.url.lower()


# ---------------------------------------------------------------------------
# POST /clicks + GET /out/{click_id}
# ---------------------------------------------------------------------------
def test_clicks_requires_auth(client):
    assert client.post("/clicks", json={"productId": CID, "surface": "feed"}).status_code == 401


def test_mint_and_redirect_plain(client, db, user1, product):
    r = client.post("/clicks", headers=_auth(_tok(user1)),
                    json={"productId": str(product.id), "surface": "feed", "cardType": "product"})
    assert r.status_code == 201
    click_id = r.json()["clickId"]

    # the click row belongs to user1, unresolved yet
    click = db.query(ProductClick).filter(ProductClick.id == click_id).one()
    assert click.user_id == user1.id and click.surface == "feed" and click.wrapped is False

    # /out redirects (302) to the product's own URL (plain, nothing approved)
    out = client.get(f"/out/{click_id}", follow_redirects=False)
    assert out.status_code == 302
    assert out.headers["location"] == product.canonical_url

    # a click_out event was fired for user1, and no user data is in the destination
    db.expire_all()
    ev = db.query(StyleEvent).filter(StyleEvent.event_type == "click_out",
                                     StyleEvent.user_id == user1.id).one()
    assert ev.entity_type == "product" and ev.source == "feed"
    assert str(user1.id) not in out.headers["location"] and user1.email not in out.headers["location"]


def test_out_rejects_url_param_open_redirect(client, db, user1, product):
    r = client.post("/clicks", headers=_auth(_tok(user1)),
                    json={"productId": str(product.id), "surface": "feed"})
    click_id = r.json()["clickId"]
    # any redirect-target query param is a hard 400 (no open-redirect surface)
    bad = client.get(f"/out/{click_id}?url=https://evil.example", follow_redirects=False)
    assert bad.status_code == 400


def test_out_unknown_click_is_404(client, db):
    assert client.get(f"/out/{CID}", follow_redirects=False).status_code == 404
    assert client.get("/out/not-a-uuid", follow_redirects=False).status_code == 404


def test_mint_unknown_product_422(client, user1):
    r = client.post("/clicks", headers=_auth(_tok(user1)),
                    json={"productId": CID, "surface": "feed"})
    assert r.status_code == 422


def test_mint_bad_surface_422(client, user1, product):
    r = client.post("/clicks", headers=_auth(_tok(user1)),
                    json={"productId": str(product.id), "surface": "hacker"})
    assert r.status_code == 422
