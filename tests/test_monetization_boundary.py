"""F1c structural boundary: ranking/composer can NEVER import monetization.

Proves it three ways: import-linter passes on the real tree; import-linter FAILS the
moment ranking imports monetization (injected probe); and payout fields live only on the
service-only affiliate_conversions table, never on the ranker's Product input.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.models import AffiliateConversion, Product, ProductClick

REPO_ROOT = Path(__file__).resolve().parents[1]
LINT = os.path.join(os.path.dirname(sys.executable), "lint-imports")


def _run_lint():
    return subprocess.run(
        [LINT], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
    )


@pytest.mark.skipif(not os.path.exists(LINT), reason="import-linter not installed")
def test_import_linter_contracts_pass():
    r = _run_lint()
    assert r.returncode == 0, f"import-linter failed unexpectedly:\n{r.stdout}\n{r.stderr}"
    assert "2 kept, 0 broken" in r.stdout


@pytest.mark.skipif(not os.path.exists(LINT), reason="import-linter not installed")
def test_import_linter_catches_ranking_importing_monetization():
    """Inject a violation into app.ranking and prove the linter breaks."""
    probe = REPO_ROOT / "app" / "ranking" / "_probe_boundary_violation.py"
    probe.write_text("from app import monetization  # deliberate boundary violation\n")
    try:
        r = _run_lint()
        assert r.returncode != 0, "import-linter did NOT catch ranking->monetization import!"
        assert "broken" in r.stdout.lower()
        assert "monetization" in r.stdout.lower()
    finally:
        probe.unlink(missing_ok=True)


def test_product_input_has_no_payout_fields():
    """The ranker's input (Product) must carry no payout/commission/network/affiliate."""
    cols = {c.name.lower() for c in Product.__table__.columns}
    forbidden = ("affiliate", "payout", "commission", "network", "click", "redirect", "deeplink")
    assert not [c for c in cols if any(f in c for f in forbidden)]


def test_payout_fields_live_only_on_service_only_table():
    """order_value + commission exist ONLY on affiliate_conversions (service-only, RLS
    no-policy) — never reachable from a product-ranking query."""
    conv_cols = {c.name for c in AffiliateConversion.__table__.columns}
    assert {"order_value", "commission", "network", "status"} <= conv_cols
    assert "user_id" not in conv_cols            # no user attribution column
    # product_clicks carries user_id (per-user RLS) but no payout.
    click_cols = {c.name for c in ProductClick.__table__.columns}
    assert "user_id" in click_cols
    assert not (click_cols & {"order_value", "commission", "payout"})


def test_no_stylist_or_ranking_source_imports_monetization():
    """Belt-and-suspenders static scan of IMPORT statements (not prose/docstrings)."""
    import re
    roots = [REPO_ROOT / "app" / "services" / "stylist", REPO_ROOT / "app" / "ranking"]
    import_re = re.compile(r"^\s*(from\s+app\.monetization|import\s+app\.monetization|from\s+app\s+import\s+(\w+\s*,\s*)*monetization)", re.M)
    offenders = [
        str(py.relative_to(REPO_ROOT))
        for root in roots for py in root.rglob("*.py")
        if import_re.search(py.read_text())
    ]
    assert not offenders, f"monetization imported by ranking/composer: {offenders}"
