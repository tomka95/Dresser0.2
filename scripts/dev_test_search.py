"""Dev diagnostic: surface WHY the shopping-search tier returns 0 candidate links.

Respects SEARCH_PROVIDER and reuses the resolver's building blocks from
app.gmail_closet.shopping_search (no reimplementation):

  * SERPER: prints the exact request body (q, gl, hl), the FULL raw Serper JSON
    response (so we can see the real field names + link values), which top-level key
    the results live under (and whether our parser reads that exact key), then a parse
    breakdown — total results, how many had a usable link, and for each dropped link
    WHY (_is_retailer_link reason: not-https / bad-host / blocked-host:<host>).
  * DATAFORSEO: prints the task_post/task_get raw responses + status/message.

Runs for BOTH "MUSERA denim jacket" (clean) and the real MUSERA closet item's built
query (looked up from the DB), so we see what the real long name produces.

Print only — stores nothing.

Usage:
    python -m scripts.dev_test_search
"""
from __future__ import annotations

import json
import logging
import sys

import httpx

from app.core.config import settings
from app.gmail_closet.shopping_search import (
    _API_BASE,
    _BLOCKED_LINK_HOSTS,
    _SERPER_RESULT_KEY,
    _SERPER_URL,
    _candidates_from_serper,
    _host,
    _is_denied_host,
    _is_landing_url,
    _is_retailer_link,
    _localize,
    _rank_candidates,
    _redact_secrets,
    _serper_locale,
    build_query,
    search_products,
)
from app.gmail_closet.image_guard import is_allowlisted_host

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)

# Top-level keys various Serper endpoints use — we report which one is actually present.
_RESULT_KEY_CANDIDATES = ("organic", "shopping", "shoppingResults", "shopping_results", "products", "results")
_PARSER_KEY = _SERPER_RESULT_KEY  # the key _candidates_from_serper() reads


def _mask(s: str) -> str:
    if not s:
        return "<MISSING>"
    if len(s) <= 4:
        return "*" * len(s)
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"


def _reject_reason(url) -> str:
    """Mirror _is_retailer_link's decision, but return WHY (or '' if it would keep)."""
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        return "not-https"
    h = _host(url)
    if not h or "." not in h:
        return "bad-host"
    for b in _BLOCKED_LINK_HOSTS:
        if h == b or h.endswith("." + b):
            return f"blocked-host:{h}"
    if _is_denied_host(h):
        return f"denied-host:{h}"
    if _is_landing_url(url):
        return f"landing-page:{h}"
    return ""  # kept (retailer if allow-listed, else unknown fallback)


def _linkish_keys(item: dict) -> dict:
    """Any key whose name suggests a URL, with its value — to spot a renamed field."""
    return {k: v for k, v in item.items()
            if isinstance(v, str) and ("link" in k.lower() or "url" in k.lower())}


def run_serper_diag(label: str, brand, name, color) -> None:
    print("\n" + "#" * 72)
    print(f"#  SERPER diagnostic — {label}")
    print("#" * 72)

    query = build_query(brand, name, color)
    gl, hl = _serper_locale(brand, name)
    print(f"  input brand/name/color: {brand!r} / {name!r} / {color!r}")
    print(f"  built query:            {query!r}")
    body = {"q": query, "gl": gl, "hl": hl}
    print(f"  request body (q,gl,hl): {json.dumps(body, ensure_ascii=False)}")
    print(f"  endpoint:               {_SERPER_URL}")
    print(f"  X-API-KEY:              {_mask(settings.SERPER_API_KEY or '')}")

    if not settings.SERPER_API_KEY:
        print("  ERROR: SERPER_API_KEY not set — cannot call Serper.")
        return

    headers = {"X-API-KEY": settings.SERPER_API_KEY, "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=20.0) as http:
            resp = http.post(_SERPER_URL, headers=headers, json=body)
    except Exception as exc:
        print(f"  ERROR issuing request: {type(exc).__name__}: {exc}")
        return

    print(f"\n  HTTP status: {resp.status_code}")
    try:
        data = json.loads(resp.text)
    except Exception:
        print("  raw response (non-JSON):")
        print("    " + _redact_secrets(resp.text or "")[:2000])
        return

    print("\n  --- FULL raw Serper JSON ---")
    print(_redact_secrets(json.dumps(data, indent=2, ensure_ascii=False)))

    # Which top-level key holds the results?
    print("\n  --- result-key detection ---")
    print(f"  top-level keys: {list(data.keys())}")
    for k in _RESULT_KEY_CANDIDATES:
        v = data.get(k)
        if isinstance(v, list):
            print(f"    {k!r}: list len={len(v)}")
    present = data.get(_PARSER_KEY)
    print(f"  our parser reads key {_PARSER_KEY!r} -> "
          f"{'present, len=' + str(len(present)) if isinstance(present, list) else 'ABSENT/!list'}")

    # Parse breakdown over whichever key actually has results.
    results_key = next((k for k in _RESULT_KEY_CANDIDATES if isinstance(data.get(k), list) and data.get(k)), None)
    results = data.get(results_key) if results_key else []
    print(f"\n  --- parse breakdown (over key {results_key!r}) ---")
    print(f"  total results: {len(results)}")
    kept = dropped = nolink = 0
    for i, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if link is None:
            nolink += 1
            print(f"   [{i}] NO 'link' field. link-ish keys present: {_linkish_keys(item)}")
            continue
        reason = _reject_reason(link)
        if reason:
            dropped += 1
            print(f"   [{i}] DROP ({reason}): {link}")
        else:
            kept += 1
            tag = "retailer" if is_allowlisted_host(_host(link)) else "fallback"
            print(f"   [{i}] KEEP ({tag}): {link}")
    print(f"\n  summary: kept={kept} dropped={dropped} missing-link={nolink}")

    ranked = _rank_candidates(_candidates_from_serper(data))
    print(f"\n  --- post-filter RANKED candidate order ({len(ranked)}; retailer-first; top "
          f"{settings.GMAIL_SEARCH_MAX_CANDIDATES} are fetched) ---")
    for j, c in enumerate(ranked):
        tag = "retailer" if is_allowlisted_host(_host(c.url)) else "fallback"
        marker = "  <-- fetched" if j < settings.GMAIL_SEARCH_MAX_CANDIDATES else ""
        print(f"   {j}. [{tag}] {c.source_domain}  {c.url}{marker}")


def _print_df_response(label: str, resp: httpx.Response) -> dict:
    print(f"\n--- {label} ---")
    print(f"  HTTP status: {resp.status_code}")
    print("  raw response body:")
    print("    " + _redact_secrets(resp.text or "").replace("\n", "\n    "))
    try:
        data = json.loads(resp.text)
        print(f"  API status_code:    {data.get('status_code')}")
        print(f"  API status_message: {data.get('status_message')}")
        return data
    except Exception:
        return {}


def run_dataforseo_diag(label: str, brand, name, color) -> None:
    print("\n" + "#" * 72)
    print(f"#  DATAFORSEO diagnostic — {label}")
    print("#" * 72)
    login, password = settings.DATAFORSEO_LOGIN, settings.DATAFORSEO_PASSWORD
    query = build_query(brand, name, color)
    location_code, language_code = _localize(brand, name)
    print(f"  built query:   {query!r}")
    print(f"  localization:  language_code={language_code!r} location_code={location_code}")
    print(f"  Basic-auth:    {_mask(login or '')} / {'set' if password else '<MISSING>'}")
    if not login or not password:
        print("  ERROR: DATAFORSEO credentials not set.")
        return
    body = [{"keyword": query, "language_code": language_code, "location_code": location_code}]
    auth = (login, password)
    with httpx.Client(timeout=20.0) as http:
        post = http.post(f"{_API_BASE}/task_post", auth=auth, json=body)
        pj = _print_df_response("task_post", post)
        task_id = next((str(t["id"]) for t in (pj.get("tasks") or []) if t.get("id")), None)
        if task_id:
            get = http.get(f"{_API_BASE}/task_get/advanced/{task_id}", auth=auth)
            _print_df_response("task_get/advanced (first poll)", get)
        else:
            print("  (no task id returned)")


def _find_real_musera():
    """Return (brand, name, color) for a real MUSERA item from the DB, or None."""
    try:
        from sqlalchemy import or_

        from app.db import SessionLocal
        from app.models import ClothingItem, IngestCandidate

        db = SessionLocal()
        try:
            it = (
                db.query(ClothingItem)
                .filter(or_(ClothingItem.brand.ilike("%musera%"), ClothingItem.name.ilike("%musera%")))
                .first()
            )
            if it:
                return it.brand, it.name, it.color_primary
            c = (
                db.query(IngestCandidate)
                .filter(or_(IngestCandidate.brand.ilike("%musera%"), IngestCandidate.name.ilike("%musera%")))
                .first()
            )
            if c:
                return c.brand, c.name, c.color
            return None
        finally:
            db.close()
    except Exception as exc:
        print(f"  (could not look up real MUSERA item: {type(exc).__name__}: {exc})")
        return None


def main() -> None:
    provider = (settings.SEARCH_PROVIDER or "serper").strip().lower()
    print("=" * 72)
    print(f"  shopping-search diagnostic — SEARCH_PROVIDER={provider!r}  "
          f"GMAIL_SEARCH_ENABLED={settings.GMAIL_SEARCH_ENABLED}")
    print("=" * 72)

    runner = run_serper_diag if provider == "serper" else run_dataforseo_diag

    # 1) clean query
    runner("clean: MUSERA denim jacket", "MUSERA", "denim jacket", None)

    # 2) the real MUSERA item's built query
    real = _find_real_musera()
    if real:
        runner("real MUSERA closet item", real[0], real[1], real[2])
    else:
        print("\n(no real MUSERA item found in clothing_items / ingest_candidates — skipped)")


if __name__ == "__main__":
    main()
