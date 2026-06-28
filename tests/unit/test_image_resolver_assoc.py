"""Unit tests for the per-item DOM association + og:image parsing (offline, pure).

No network, no DB — these exercise app.gmail_closet.image_resolver's HTML reasoning:
mapping each <img>/<a> to the right line item by proximity, classifying cid vs remote
sources, filtering tracking pixels / logos, and reading og:image off a product page.
"""
from app.gmail_closet.image_resolver import ResolverItem, associate, extract_og_image


MULTI_ITEM_HTML = """
<html><body>
  <img src="https://track.example.com/pixel.gif" width="1" height="1">
  <img src="https://cdn.shopify.com/logo.png" alt="Acme Store Logo">
  <table><tr>
    <td>
      <a href="https://shop.nike.com/air-max-90">
        <img src="https://images.nike.com/airmax90.jpg" alt="Air Max 90 Sneakers">
      </a>
      <div>Air Max 90 Sneakers</div><div>$129.99</div>
    </td>
    <td>
      <a href="https://shop.nike.com/dri-fit-tee">
        <img src="https://images.nike.com/drifit.jpg" alt="Dri-FIT Running Tee">
      </a>
      <div>Dri-FIT Running Tee</div><div>$35.00</div>
    </td>
  </tr></table>
</body></html>
"""


def test_multi_item_maps_each_image_to_its_item():
    items = [
        ResolverItem(name="Air Max 90 Sneakers", unit_price=129.99),
        ResolverItem(name="Dri-FIT Running Tee", unit_price=35.0),
    ]
    refs = associate(MULTI_ITEM_HTML, items)

    assert refs[0].remote_imgs == ["https://images.nike.com/airmax90.jpg"]
    assert refs[0].product_links == ["https://shop.nike.com/air-max-90"]
    assert refs[1].remote_imgs == ["https://images.nike.com/drifit.jpg"]
    assert refs[1].product_links == ["https://shop.nike.com/dri-fit-tee"]


def test_tracking_pixel_and_logo_are_filtered():
    items = [ResolverItem(name="Air Max 90 Sneakers", unit_price=129.99),
             ResolverItem(name="Dri-FIT Running Tee", unit_price=35.0)]
    refs = associate(MULTI_ITEM_HTML, items)
    all_imgs = refs[0].remote_imgs + refs[1].remote_imgs
    assert "https://track.example.com/pixel.gif" not in all_imgs
    assert "https://cdn.shopify.com/logo.png" not in all_imgs


def test_inline_cid_is_classified_as_inline():
    html = (
        '<table><tr><td>'
        '<img src="cid:prod1@mail" alt="Blue Hoodie">'
        '<div>Blue Hoodie</div><div>$60</div>'
        '</td></tr></table>'
    )
    refs = associate(html, [ResolverItem(name="Blue Hoodie", unit_price=60)])
    assert refs[0].inline_cids == ["prod1@mail"]
    assert refs[0].remote_imgs == []


def test_single_item_fallback_takes_the_only_image():
    html = (
        '<table><tr><td>'
        '<img src="https://cdn.shopify.com/files/p123.jpg" alt="Product">'
        '</td></tr></table>'
    )
    refs = associate(html, [ResolverItem(name="Totally Different Name", unit_price=None)])
    assert refs[0].remote_imgs == ["https://cdn.shopify.com/files/p123.jpg"]


def test_no_html_returns_empty_refs():
    refs = associate("", [ResolverItem(name="x")])
    assert refs[0].inline_cids == [] and refs[0].remote_imgs == [] and refs[0].product_links == []


def test_og_image_absolute_and_relative():
    abs_html = '<html><head><meta property="og:image" content="https://images.nike.com/og.jpg"></head></html>'
    assert extract_og_image(abs_html, "https://shop.nike.com/") == "https://images.nike.com/og.jpg"

    rel_html = '<head><meta property="og:image" content="/img/p.jpg"></head>'
    assert extract_og_image(rel_html, "https://shop.nike.com/") == "https://shop.nike.com/img/p.jpg"

    twitter_html = '<head><meta name="twitter:image" content="https://images.nike.com/t.jpg"></head>'
    assert extract_og_image(twitter_html, "https://shop.nike.com/") == "https://images.nike.com/t.jpg"

    assert extract_og_image("<head></head>", "https://shop.nike.com/") is None
