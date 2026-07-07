# Tailor — Architecture & Scale-Readiness Audit

**Branch:** `chore/scale-housekeeping` · **Date:** 2026-07-07 · **Scope:** behavior-preserving structural/hygiene pass.
**Invariants honored:** Alembic is the source of truth (head `0025`); no DB touched, no migrations edited, schema unchanged; import-linter contracts kept green.

This document is the Phase-1 audit. It is READ-ONLY analysis plus a proposed plan — no source under `app/` or `apps/web/src` was changed to produce it. Phase-2 safe cleanups (dead-file deletion, artifact untracking) are recorded in the appendix and were executed on this branch.

---

## 0. How to read this

- **§1 Security / Privacy / RLS** — read first. Nothing here was silently "fixed"; each item is flagged with file:line and a recommendation.
- **§2 Ranked scale-risk list** — the prioritized backlog.
- **§3–§13** — detailed findings per dimension.
- **§14 TODO inventory** — every marker, grouped.
- **§15 Target architecture** + **§16 Phased plan** — the refactor proposal (each phase independently mergeable, behavior-preserving, with a test-proof).
- **§17 Appendix** — exact Phase-2 changes, gate commands + results, stale-branch delete commands.

Baseline gates (this branch, before Phase-2 edits): **pytest 489 passed / 1 skipped**, **lint-imports 2/2 KEPT**, **alembic check: no new operations, head `0025`**, **tsc 0**, **vitest 113/113**, **next build ✓**.

---

## 1. Security / Privacy / RLS findings (flagged, not fixed)

Ranked by severity. None of these were changed — each is a decision for Guy.

### S1 — CRITICAL (verify immediately): default JWT secret + live legacy dual-accept path
- `app/core/config.py:466` — `JWT_SECRET_KEY: str = "change-this-secret-key-in-production"` is a **hardcoded default**.
- `app/dependencies.py:71-79` — `get_current_user` still accepts legacy custom JWTs verified with `settings.JWT_SECRET_KEY` (dual-accept during the Supabase cutover). `app/security.py:33` signs with the same key.
- **Impact:** if `JWT_SECRET_KEY` is unset in any deployed environment, the fallback secret is public (it's in this repo). An attacker can mint a legacy token with `{"sub": "<any-user-uuid>"}` and impersonate any user — full account takeover — because the legacy path resolves the user by `sub` (`dependencies.py:82-90`).
- **Action:** (1) confirm `JWT_SECRET_KEY` is set to a strong secret in every non-local env NOW; (2) schedule retirement of the legacy custom-JWT path once Supabase Auth is the sole issuer (removes `bcrypt`, `/signup`, `/login`, and this foot-gun). Tracked in memory as the Supabase Auth cutover.

### S2 — HIGH: unauthenticated write endpoints in `main.py`
- `main.py:104-118` `POST /users` — creates a user from a query param, **no auth**.
- `main.py:121-143` `POST /users/{user_id}/clothing` — writes a clothing item to an **arbitrary `user_id` in the path, no auth** (IDOR write / data-pollution surface; bypasses RLS because it runs on the owner connection).
- `main.py:146-171` `POST /signup`, `main.py:174-193` `POST /login` — legacy custom-auth (bcrypt), pre-Supabase.
- **Action:** gate or delete `/users` and `/users/{user_id}/clothing` (they look like dev scaffolding; the real create paths are authed routers). Decide `/signup`+`/login` as part of S1. These are behavior-bearing, so they are **flagged, not removed** in Phase 2.

### S3 — MEDIUM: CORS is hardcoded to localhost
- `main.py:55-64` — `allow_origins=["http://localhost:3000","http://127.0.0.1:3000"]`, `allow_credentials=True`, `allow_methods/headers=["*"]`.
- **Impact:** not a leak today, but the allowlist must become env-driven before a real frontend origin ships; `allow_headers=["*"]` with credentials is broad.
- **Action:** move origins into `Settings` (`CORS_ALLOWED_ORIGINS`), tighten methods/headers.

### S4 — MEDIUM: `python-jose` is on the JWT verification hot path
- Used at `app/supabase_auth.py:34`, `app/dependencies.py:7`, `app/security.py:4`, `app/core/gmail_oauth_state.py:21`. It verifies **Supabase** access tokens — not removable.
- `python-jose` has a CVE history (algorithm-confusion / JWT-bomb, e.g. CVE-2024-33663/33664). Current pin is `>=3.3.0`.
- **Action:** raise the floor to a patched release (`>=3.4.0`) or migrate the verification to `PyJWT`. Do **not** remove.

### S5 — LOW/INFO: RLS coverage is complete; two adjacent notes
- **Good news:** all **29 tables have RLS enabled** — 20 with per-user `auth.uid() = user_id` policies, 9 service-only-by-design (see §11). No per-user personal-data table lacks a policy. No RLS gap found.
- **Note A — no `GRANT`s in version control.** No migration issues `GRANT`s; the RLS-enforced `authenticated` role (`app/services/stylist/rls.py:104`) relies entirely on Supabase's out-of-band default schema grants + the RLS policies. This is functional but means table-access for that role is not reproducible from the repo alone. Consider adding explicit grants to a migration, or documenting the dependency.
- **Note B — per-worker in-process rate limiters.** `POST /events` (`app/api/routes/events.py:55`) and chat quotas use a `threading.Lock`-guarded in-memory limiter (`config.py:234` admits "In-process (per uvicorn worker); a shared limiter (Redis) is the production upgrade"). Chat quotas/rate-windows are already Postgres-backed (`chat_usage`, `chat_rate_windows`) — the events limiter is the outlier. At >1 worker, the events rate limit is effectively `N_workers × limit`.

### S6 — LOW: user-id PII in logs (no secrets/bytes leaked)
- `app/gmail_closet/gmail_oauth_service.py:65,106` log `user_id` via f-string; `:111,114` log raw exceptions. No emails, tokens, or image bytes are logged anywhere (image logging is `len(...)` only — verified across `ai_provider.py`, `nano_banana.py`, `seedream.py`). The single redaction helper is `app/db.py:132 _redact()` (DB-URL creds only).
- **Action:** add a small PII/token log-scrubber; downgrade the per-user-id info logs or hash the id.

**Positive security posture worth preserving:** the RLS-enforced agent connection (`app/services/stylist/rls.py`) is correctly transaction-scoped (`SET LOCAL role authenticated` + `set_config('request.jwt.claims', …, true)`), fail-loud (`RlsSetupError` → 503, never a silent bypass). Uploads are sniffed/sanitized/EXIF-stripped (`main.py:209-220`, `app/utils/image_validation.py`). Monetization is walled off from ranking by import-linter. `.env` is untracked; no secrets or API keys are committed in code (scanned).

---

## 2. Ranked scale-risk issue list

| # | Risk | Severity | Where | Fix summary |
|---|------|----------|-------|-------------|
| R1 | **No durable job system** — request-path fire-and-forget for long/costly work | 🔴 High | `gmail_ingest.py:229` (full email sync), `photo_ingest.py:277`, `closet.py:278`, `chat.py:222-230` (raw daemon thread), `chat_ingest.py:137-141` | Introduce a durable queue/worker; make ingest resumable; strand-proof `IngestRun` rows |
| R2 | **Per-worker in-process state** won't scale horizontally | 🔴 High | 14 `threading.Lock` sites: `events.py:55`, `supabase_auth.py:51`, `image_resolver.py:158`, `image_guard.py:118`, `image_verify.py:92`, `shopping_search.py:104`, `usage.py:105`, `costs.py:46`, `limits.py:186`, `collage.py:88`, `image_generation/base.py:137`, `monetization/routes.py:43` | Move shared limiter/cache state to Postgres/Redis; keep per-worker caches read-through |
| R3 | **Cyclic package coupling** `services ⇄ gmail_closet`, `services ⇄ photo_closet` | 🟠 Med-High | `stylist/costs.py:12`, `stylist/agent.py` (top-level `gmail_closet.usage`); `gmail_closet/image_verify.py`, `review_service.py`, `extractor.py` → `services.ai_provider` | Extract `ai_provider` + usage/cost accounting into a neutral layer; break the 2-cycles |
| R4 | **God module `models.py`** (28 ORM classes, imported by 40+ files) | 🟠 Med | `app/models.py` (1368 LOC) | Split into a `models/` package by bounded context; re-export from `__init__` (schema-neutral) |
| R5 | **Decentralized DB/storage config** — two sources of truth | 🟠 Med | `app/db.py` (11 raw `os.getenv`), `app/utils/supabase_storage.py:16-18,34-35` duplicate `DB_*`/`SUPABASE_S3_*` already on `Settings` | Route all env through `core/config`; `db.py`/storage read `settings` |
| R6 | **Ad-hoc provider seam** `SEARCH_PROVIDER` diverges from the gold-standard pattern | 🟠 Med | `app/gmail_closet/shopping_search.py:289,321-324` | Converge onto the `GenerationProvider`/`FeedProvider` shape (§8) |
| R7 | **Business logic in `main.py`** (auth, signup/login, user + clothing creation, outfit-upload orchestration) | 🟠 Med | `main.py:104-256` | Move handlers into routers/services; `main.py` becomes wiring only |
| R8 | **God module `ai_provider.py`** — mega-`chat()`, hardcoded model strings | 🟡 Low-Med | `app/services/ai_provider.py` (841 LOC); hardcoded models at `:390,477,548,749` | Decompose `chat()`/response-parsing; route model names through `settings` |
| R9 | **God module `image_resolver.py`** — ~5 concerns, nested closures | 🟡 Low-Med | `app/gmail_closet/image_resolver.py` (795 LOC) | Split cache / html-parse / scoring / resolve |
| R10 | **`utils` layer violation** — reaches up into models + DB | 🟡 Low | `app/utils/image_blob_store.py:65` (`from app.models import ImageBlob`, `from app.db import SessionLocal`) | Make `utils` a true leaf; inject session/model |
| R11 | **DB engine has no explicit pool sizing** | 🟡 Low | `app/db.py:124-129` (default QueuePool 5/10) | Set `pool_size`/`max_overflow`/`pool_recycle` from config for pooler/pgBouncer |
| R12 | **No structured logging / correlation IDs; batch scripts get no log config** | 🟡 Low | `main.py:5-8` only; `scripts/*`, `ranking/job.py` run without `basicConfig` | Central logging setup importable by scripts; add request-id middleware |
| R13 | **3 silent non-rollback exception swallows** | 🟡 Low | `fetch_service.py:211`, `extraction_service.py:546`, `generation_service.py:448` | Add a `logger.warning` before `pass` |
| R14 | **Config god-object** — `Settings` is ~120 flat fields | 🟢 Info | `app/core/config.py` | Optional: nested settings groups (LLM/Gmail/Ranking/Chat/DB) |
| R15 | **Backend↔frontend contract drift** — Python schemas vs `@tailor/contracts` unlinked | 🟢 Info | `docs/contracts-notes.md` | Consider generating one from the other, or a contract test |

---

## 3. Module / package layout & layering

**Packages:** `app/api` (routes) · `app/core` (config, crypto, oauth-state) · `app/services` (+ `stylist`, `tagging`, `image_generation`) · `app/gmail_closet` · `app/photo_closet` · `app/ranking` · `app/monetization` · `app/utils`. `app/models.py` + `app/db.py` are top-level modules.

**Import-edge map (by import-line count, `app/` + `main.py`):**

| Edge | Count | Verdict |
|------|-------|---------|
| api → services | 18 | ✅ down |
| services → core | 17 | ✅ |
| services → models | 17 | ✅ |
| gmail_closet → models | 14 | ✅ |
| api → models | 10 | ⚠️ routes touch ORM directly |
| ranking → services | 8 | ✅ |
| gmail_closet → services | 7 | ⚠️ cycle |
| services → gmail_closet | 3 | ⚠️ cycle |
| services → photo_closet | 4 | ⚠️ cycle |
| photo_closet → services | 3 | ⚠️ cycle |
| utils → models | 1 | ❌ layer violation (`image_blob_store.py:65`) |
| utils → db | 1 | ❌ layer violation |
| models → core | 1 | ⚠️ lazy in-fn (`models.py:1171`) |

- **`core` is a clean leaf** (imports nothing from `app` outside `core`). Good anchor for the target layering.
- **Two genuine package 2-cycles** (`services ⇄ gmail_closet`, `services ⇄ photo_closet`) — see R3. They don't crash at import only because several cross-imports are function-local, but `stylist/costs.py:12` and `agent.py` import `gmail_closet.usage` at module top → `services.stylist` cannot load without `gmail_closet`, and `gmail_closet.image_verify` cannot load without `services`. Latent import-order landmine; blocks splitting these into separable units. **Root cause:** `app/gmail_closet/usage.py` (shared cost/usage accounting) lives inside a feature package but is consumed by `services.stylist`.
- **God modules:** `models.py` (1368, 28 tables), `ai_provider.py` (841), `image_resolver.py` (795). See R4/R8/R9.
- `gmail_closet` and `photo_closet` do **not** import each other except one benign one-way edge (`photo_closet/generation_service.py → gmail_closet`).

---

## 4. Config & secrets

- **Centralized surface:** one `pydantic_settings.BaseSettings` (`app/core/config.py`, ~120 fields, `settings` singleton). `env_file=".env"`, `extra="ignore"`. Well-centralized but a god-object (R14). `app/monetization/config.py` is **not** a second source — it's thin typed accessors over `settings` (fine).
- **Decentralization problem (R5):** raw env reads that bypass `Settings`:
  - `app/db.py` — `DATABASE_URL`, `DATABASE_URI`, `DB_USER/PASSWORD/HOST/PORT/NAME`, `LOCAL_DB`, `USE_SQLITE`, `ALLOW_REMOTE_TEST_DB`, `PYTEST_CURRENT_TEST` (11 reads). `DB_*` also exist as `Settings` fields (`config.py:422-426`) → **two sources of truth**.
  - `app/utils/supabase_storage.py:16-18,34-35` — `SUPABASE_S3_*` read raw, also on `Settings` (`config.py:428-432`).
  - Also: `app/db.py:14` calls `load_dotenv()` a second time (config.py already loads `.env`).
- **Secrets in code:** none committed (scanned `app/`, `main.py`, `scripts/`, `apps/web/src` for `sk-…`, `AIza…`, `eyJ…`, key/secret literals → clean). The only literal is the default `JWT_SECRET_KEY` (S1). `.env` is untracked. At-rest Gmail-token encryption key (`GMAIL_TOKEN_ENC_KEY`) is env-only by design (`config.py:457-461`).
- **Full env-var inventory:** see §4a below.

### 4a. Env-var inventory (by area, from `Settings` + raw reads)
- **LLM/AI:** `LLM_PROVIDER`, `OPENAI_API_KEY`(unused), `GEMINI_API_KEY`, `GEMINI_EXTRACT_MODEL`, `GEMINI_EXTRACT_ESCALATION_MODEL`, `GEMINI_DETECT_MODEL`, `GMAIL_VERIFY_MODEL`, `GENERATION_VERIFY_MODEL`, `GENERATION_VERIFY_MEDIA_RESOLUTION`, `STYLIST_MODEL`, `STYLIST_LITE_MODEL`, `STYLIST_ESCALATION_MODEL`, `ENRICHMENT_MODEL`, `DISTILL_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_TASK_TYPE_DOCUMENT`, `EMBEDDING_VERSION`, `NANO_BANANA_MODEL`.
- **Cost rates:** `GEMINI_FLASH_LITE_*`, `GEMINI_FLASH_*`, `GEMINI_PRO_*`, `SERPER_USD_PER_CREDIT`, `FLUX_KONTEXT_USD_PER_IMAGE`, `SEEDREAM_USD_PER_IMAGE`, `NANO_BANANA_USD_PER_IMAGE`.
- **Gmail ingest:** `GMAIL_EXTRACT_*`, `GMAIL_VERIFY_*`, `GMAIL_SEARCH_*`, `GMAIL_FETCH_MAX_PER_RUN`, `GMAIL_FEED_ENABLED`, `GMAIL_IMAGE_FILL_MAX_CANDIDATES`, `GMAIL_SELF_HEAL_MAX_ITEMS`, `GMAIL_MAX_YEARS`, `GMAIL_IMAP_TIMEOUT`.
- **Search/feed providers:** `SEARCH_PROVIDER`, `SERPER_API_KEY`, `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`.
- **Image generation:** `GENERATION_ENABLED`, `GENERATION_PROVIDER`, `BFL_API_KEY`, `FAL_API_KEY`, `GENERATION_*` caps/timeouts.
- **Photo ingest:** `PHOTO_SESSION_TTL_HOURS`, `PHOTO_DETECT_MAX_CONCURRENCY`, `IMAGE_API_*`.
- **Chat (S2):** `CHAT_MAX_*`, `CHAT_HISTORY_WINDOW`, `CHAT_MAX_TOOL_ROUNDS`, `CHAT_RETRIEVAL_LIMIT`, `CHAT_TURN_TIMEOUT_SECONDS`, `CHAT_RATE_LIMIT_PER_MINUTE`, `CHAT_MAX_CONCURRENT_STREAMS`, `CHAT_DAILY_TURN_QUOTA`, `CHAT_DAILY_COST_QUOTA_USD`, `CHAT_RETENTION_DAYS`, `CHAT_RLS_ENFORCED`.
- **Distill (S3):** `DISTILL_*`.
- **Ranking (F2):** `RANKING_W_*`, `RANKING_BLEND_*`, `RANKING_GAP_*`, `RANKING_PRICE_*`, `RANKING_FATIGUE_DECAY`, `RANKING_MMR_LAMBDA`, `RANKING_EXPLORATION_EPSILON`, `RANKING_CATEGORY_CALIBRATION`, `RANKING_OUTFIT_*`, `RANKING_FEED_PAGE_SIZE`.
- **Events/Onboarding:** `EVENTS_MAX_*`, `EVENTS_RATE_LIMIT_PER_MINUTE`, `ONBOARDING_MAX_*`, `ONBOARDING_CONFIDENCE_*`.
- **Monetization:** `SOVRN_SITE_ID`, `SKIMLINKS_PUBLISHER_ID`, `MONETIZATION_DIRECT_DEEPLINK_ENABLED`, `CLICK_RATE_LIMIT_PER_MINUTE`, `SHEIN_AFFILIATE_ID`, `ALIEXPRESS_AFFILIATE_ID`.
- **DB/storage:** `DB_*`, `DATABASE_URL`/`DATABASE_URI`, `LOCAL_DB`, `USE_SQLITE`, `ALLOW_REMOTE_TEST_DB`, `SUPABASE_S3_*`, `SUPABASE_PUBLIC_BASE_URL`.
- **Auth/Gmail OAuth:** `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `GMAIL_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI/SCOPE`, `GMAIL_OAUTH_STATE_SECRET`, `GMAIL_OAUTH_STATE_TTL_SECONDS`, `GMAIL_TOKEN_ENC_KEY`, `SUPABASE_PROJECT_REF`, `SUPABASE_URL`, `SUPABASE_JWKS_URL`, `SUPABASE_JWT_ISSUER`, `SUPABASE_JWT_AUDIENCE`, `SUPABASE_JWKS_CACHE_TTL_SECONDS`.
- **Frontend (`apps/web`):** `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (public by design).

---

## 5. Provider seams — consistency

The codebase already declares a gold standard (`image_generation/base.py:12` — "THE SEAM (mirrors FeedProvider)"), but applied it unevenly.

| Seam | Selector env (default) | Enable flag | Mechanism | Common interface | Null fallback | Verdict |
|------|------------------------|-------------|-----------|------------------|---------------|---------|
| **GenerationProvider** | `GENERATION_PROVIDER` (`flux_kontext`) | `GENERATION_ENABLED` | factory + **registry dict** + if/elif (`base.py:170,185`) | ✅ `@runtime_checkable Protocol` + typed Request/Result | ✅ `NullGenerationProvider` | ⭐ **gold standard** |
| **FeedProvider** | *(one impl)* | `GMAIL_FEED_ENABLED` | factory + singleton (`feed_provider.py:84`) | ✅ Protocol + Result | ✅ `NullFeedProvider` | ⭐ correct, scaled down |
| **SEARCH_PROVIDER** | `SEARCH_PROVIDER` (`serper`) | `GMAIL_SEARCH_ENABLED` | **if/elif over free functions** (`shopping_search.py:289,321`) | ❌ none (shared return only) | returns `[]` | 🔧 refactor to gold standard (R6) |
| **AIProvider** | `LLM_PROVIDER` (`gemini`) | — | **if/else-raise in class `__init__`** (`ai_provider.py:66-78`) | ❌ none (single concrete class) | raises | 🔧 give it a Protocol or rename Gemini-only; move hardcoded model strings `:390,477,548,749` to `settings` (R8) |
| **STYLIST_MODEL** | `STYLIST_MODEL`/`_LITE`/`_ESCALATION` | — | model-**string** routing into AIProvider (`agent.py:180-184`) | n/a (1 provider) | fail-open to Flash | ✅ clean; not a provider seam — label as model routing |
| **Embeddings** | `EMBEDDING_MODEL` | — | injected `provider` param → `AIProvider.embed_texts` | duck-typed | returns `False` | ✅ clean; import-time dim-parity assert (`product_embeddings.py:69-92`) is the strongest guard in the repo |

**Recommendation:** unify on the `GenerationProvider`/`FeedProvider` pattern (Protocol contract + Null default + factory + optional registry + enable flag + centralized `settings`). Port `SEARCH_PROVIDER` first; give `AIProvider` a real interface (or rename to reflect it's Gemini-only today). `STYLIST_MODEL`/Embeddings are model-name routing through the one provider — not swap points; don't over-abstract them.

---

## 6. DB access at scale

- **Single global engine** (`app/db.py:214`), `pool_pre_ping=True`, `connect_timeout=5`, `sslmode=require`. **No explicit `pool_size`/`max_overflow`/`pool_recycle`** → SQLAlchemy defaults (5 + 10 overflow) (R11). With Supabase's PgBouncer in transaction mode this is usually fine, but sizing should be config-driven and matched to worker count.
- **Session handling:** `get_db()` dependency yields `SessionLocal()` and closes (`dependencies.py:25-30`) — standard. The RLS-enforced agent path opens its own connection/transaction (`rls.py`) — correct and isolated (§1 positive note).
- **N+1 risk:** routes import `models` directly and query inline (`api → models` ×10); worth an eyes-on pass on the closet/feed list endpoints for missing `selectinload`/`joinedload`, but no systemic N+1 was confirmed in this static pass. Flagged for a targeted review, not asserted.
- **Background work (R1):** no job queue ("Redis is not part of this stack", `config.py:302`). Two dispatch idioms coexist: Starlette `BackgroundTasks` (routes) and raw daemon `threading.Thread` (chat SSE post-processing). Worst offender: `gmail_ingest.py:229` runs a **full multi-minute, multi-API, cost-incurring email sync** as fire-and-forget; a worker restart strands the `IngestRun` row (created `:224`) at `status="running"` forever with no retry.
- **Nightly jobs are all manual CLIs** (`app/ranking/job.py`, `run_redistill`, enrichment backfill) invoked only via `scripts/dev_*`. No scheduler is wired in the repo.

---

## 7. Dev-script sprawl (`scripts/`)

15 files, all `if __name__=="__main__"` CLIs, flat in `scripts/`:
- **Backfills/self-heal:** `dev_backfill_images.py`, `dev_enrich_backfill.py`, `dev_verify_images.py`, `dev_self_heal.py`, `dev_generation_self_heal.py`.
- **Ingest:** `dev_run_ingest.py`, `dev_confirm_ingest.py`, `dev_ingest_product.py`.
- **Ranking/learning:** `dev_wardrobe_gap.py`, `dev_redistill.py`.
- **Search/gen tooling:** `dev_test_search.py`, `dev_generation_bakeoff.py` (41 KB), `gen_taste_deck.py` (21 KB).
- **Cost:** `dev_user_cost.py`. **Shell:** `dev-backend.sh`, `dev-frontend.sh`.
- **Problem:** these mix *operational jobs that must run in production on a schedule* (redistill, wardrobe-gap, enrichment backfill, self-heal) with *one-off developer tools* (bakeoff, test-search, taste-deck gen). None configure logging.
- **Proposal:** split into `scripts/ops/` (scheduled/operational — the real entry points a scheduler will call) vs `scripts/dev/` (throwaway tooling); give ops scripts a shared `logging` bootstrap; the ops jobs become the seam a future scheduler targets.

---

## 8. Logging & error handling

- **Logging:** single `logging.basicConfig` at `main.py:5-8` (plain text, one handler), then idiomatic `logger = logging.getLogger(__name__)` in ~70 modules — consistent. Gaps: no structured/JSON logs, no correlation/request IDs (R12); standalone scripts/jobs get no config and fall to root `WARNING`. Only 4 `print()` in `app/`, all in `utils/version_check.py` (bootstrap, pre-logging) — acceptable.
- **Redaction:** one helper, `db.py:132 _redact()` (DB-URL creds). No general token/PII scrubber (S6).
- **Error handling:** routes consistently use `HTTPException` (per-router counts 5–14). **No bare `except:`** anywhere. Most broad catches log + rollback (good). Three genuinely silent non-rollback swallows to fix (R13): `fetch_service.py:211`, `extraction_service.py:546`, `generation_service.py:448`. The `ranking/feed.py:235,247` catches are deliberate ("never let one card 500 the feed") and fine.

---

## 9. Frontend (`apps/web`) post-redesign

- **Canonical UI system = `components/ds/*`** (barrel `ds/index.ts` imported by 56 files). `components/ui/*` is legacy shadcn scaffolding: only 3 files are alive and non-overlapping (`ItemImage.tsx` — 13 sites, canonical image; `ConfidenceDot.tsx` — 2 sites; `dialog.tsx` — Radix primitive layered under `ds/DialogFrame`). The rest were dead (removed in Phase 2, §17). **No leftover duplicate button/modal system remains** after cleanup — `ds/Button` is the sole button system; `ds/DialogFrame` (over Radix `ui/dialog`) is the sole modal.
- **API-client layer:** consistent per-domain pattern — each module declares `API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'`, injects `Authorization: Bearer` via `getAccessToken()`, raw `fetch`. **No shared fetch wrapper**, and `API_BASE_URL` is duplicated in every module — the one worthwhile frontend consolidation (a `lib/api/http.ts` client). Two `*Client.ts` files (`outfitsClient.ts`, `closetClient.ts`) are in-memory **mocks** pending real endpoints (`TODO(api)`), reached only through `outfits/index.ts`; `closet/index.ts` is the real, live closet client.
- **Shared types:** `@tailor/contracts` (zod, workspace pkg) imported by 23 files — the correct pattern, used consistently. `components/chat/types.ts` is a legit chat view-model layer, not a duplicate.
- **Dead components removed** (Phase 2, all grep-proven zero-ref): see §17. `lib/auth/storage.ts` remains but is `@deprecated` (re-export shim) — kept (may still be imported by external callers); candidate for a later sweep.

---

## 10. Dependency audit

**Python (`requirements.txt`):**
- **Remove (no import site anywhere):** `openai` (only `OPENAI_API_KEY` config field exists; AI is 100% `google.genai`), `supabase` (Python SDK never imported — Supabase is reached via httpx/jose/boto3), `google-auth-oauthlib` (zero refs; OAuth is hand-rolled via httpx + `google.oauth2.credentials`).
- **Likely-remove:** `email-validator` (no `EmailStr` in the tree, so pydantic never pulls it).
- **Keep-but-act:** `python-jose` (S4 — bump floor), `bcrypt` (legacy `/signup`+`/login` only — kill with S1 or document).
- **Annotate:** ceiling pins `google-auth<2.42.0`, `google-genai<1.50.0` have no recorded rationale — add a "why" + a bump cadence so security patches aren't frozen.
- No undeclared deps; every third-party import maps to a requirement.

**Node (`apps/web/package.json`):** clean. No date-lib bloat, single HEIC path (`heic-to`), React 18 / Next 14 / types all consistent, no EOL majors. `lottie-web` (~250 KB) is used in exactly one loader (`ds/loaders/LottieMark.tsx:32`) — optional low-leverage drop. `packages/contracts` is a real shared package, not scaffold.

> Dependency removals are **not** in Phase 2 (Phase 2 is narrowly scoped to dead files/artifacts); they're in the phased plan because runtime/plugin loading isn't visible to static grep — confirm against deploy tooling first.

---

## 11. RLS coverage — all 29 tables

Every table has `ENABLE ROW LEVEL SECURITY`. **20 per-user** (`auth.uid() = user_id`, full CRUD): `users`, `clothing_items`, `item_images`, `google_accounts`, `processed_messages`, `ingest_candidates`, `ingest_runs`, `processed_uploads`, `photo_detect_sessions`, `item_embeddings`, `style_events`, `style_profiles`, `style_preferences`, `preference_signals`, `conversations`, `chat_messages`, `saved_outfits`, `chat_usage`, `product_clicks`, `user_wardrobe_gap`.

**9 service-only by design** (RLS enabled, no policy → deny-all to `anon`/`authenticated`; only the owner/service role reaches them; each has no `user_id`): `weather_cache`, `waitlist`, `alembic_version`, `image_blobs`, `product_image_cache`, `chat_rate_windows`, `products`, `product_embeddings`, `affiliate_conversions` (payout data — deliberately invisible to the ranker, reinforcing the import-linter wall).

**No RLS-disabled tables. No per-user table missing a policy. No gap.** (Dropped in `0018`: `user_preferences`, `user_preference_events` — superseded by the stylist substrate; not counted.) See §1-S5 for the two adjacent notes (no VC grants; events limiter per-worker).

---

## 12. Naming consistency

- **Routers** are consistent (`prefix` + `tags`): `/closet`, `/photo/ingest`, `/gmail/oauth`, `/gmail/ingest`, `/chat`, `/events`, `/onboarding`, `/shop`, `/auth`, `/outfits` (feedback), monetization (no prefix, tag only).
- **Outlier:** `main.py` holds un-prefixed, un-tagged handlers (`/signup`, `/login`, `/users`, `/users/{user_id}/clothing`, `/outfit-image`, `/health`) outside the router pattern — folds into R7.
- Tables are `snake_case` plural, consistent. `user_wardrobe_gap` is singular (minor). Routes are lowercase, path params `{snake_case}`.

---

## 13. Docs & misc hygiene

- `README.md` is **stale**: instructs "Set your OpenAI API key" and "Place a test outfit image at `Images/test_outfit.jpg`" — the app is Gemini + Supabase now, and that path doesn't exist. Rewrite for the current stack.
- `migrations/` (top-level) holds 2 **pre-Alembic** loose SQL files (`add_closet_indexes.sql`, `add_gmail_sync_completed_at.sql`) + a README — orphaned relative to the Alembic chain. Fold their intent into a note or delete after confirming they're already in the baseline.
- `main.py:273` — `# TODO: Remove this auto-open behavior before production` (dev Swagger auto-open thread).

---

## 14. Full TODO / dead-code inventory

**Markers (8 in-scope + 2 in `packages/contracts`):**

| file:line | context |
|-----------|---------|
| `app/services/ai_provider.py:482` | `# TODO: Extract raw image bytes from the response` (unfinished Gemini image-gen parse) |
| `app/services/ai_provider.py:489` | `# TODO: Raise value error here doesnt point to the problem, FIX IT` (bad error path) |
| `app/services/ai_provider.py:486-488` | commented example response-shape lines (the only real commented-out code block in the repo) |
| `app/gmail_closet/gmail_oauth_client.py:142` | `# TODO: Remove this debug logging` |
| `main.py:273` | `# TODO: Remove this auto-open behavior before production` |
| `apps/web/src/lib/api/outfitsClient.ts:7` | `TODO(api): Replace with POST /api/outfits/suggest …` (mock client) |
| `apps/web/src/lib/api/closetClient.ts:8` | `TODO(api): Swap this module with GET/POST /api/closet` (mock client) |
| `apps/web/src/lib/api/outfits/index.ts:9` | `TODO(api): Replace with real POST /api/outfits/suggest` |
| `apps/web/src/lib/auth/storage.ts:2` | `@deprecated Legacy import path` (re-export shim) |
| `packages/contracts/src/closet.ts:46,72` | `TODO: define expected analysis_raw JSON shape` (×2) |

**Silent `except: pass` cluster (20; the largest latent-debt group, concentrated in `gmail_closet`):** `distill.py:350,708`; `composer.py:326`; `limits.py:180`; `enrichment.py:378,484`; `image_resolver.py:317`; `extraction_service.py:547`; `usage.py:194,227`; `image_fill_service.py:401`; `fetch_service.py:212,481`; `gmail_oauth_client.py:230`; `product_ingest.py:228`; `shopping_search.py:318`; `generation_service.py:419,453,686`; `ranking/features.py:221`. (Most are rollback-guards or commented-intentional; the 3 in R13 are the genuinely silent non-rollback ones.)

**Interface stub bodies (intentional):** `image_generation/base.py:113`, `feed_provider.py:63` (`...`). No `raise NotImplementedError` in `app/`.

**`print()` in `app/` (bootstrap only):** `utils/version_check.py:28,38,49,53`.

**Tracked generated artifacts (untracked in Phase 2):** 4× `.DS_Store`, `.cursor/debug.log`, 8× `bakeoff_out/*`, 3× `outfit_outputs/*/summary.json`.

**Empty `__init__.py`:** `app/api/__init__.py`, `app/api/routes/__init__.py`, `app/core/__init__.py`, `scripts/__init__.py` (all fine — package markers).

---

## 15. Target architecture

A pragmatic layered target that preserves every contract and the schema:

```
app/
  core/            # leaf: config, logging setup, crypto, oauth-state, clock. Imports nothing from app/*.
    config/        # Settings split into nested groups (LLM, Gmail, Ranking, Chat, DB, Auth, Monetization)
    logging.py     # single setup importable by main AND scripts/ops
  models/          # ORM package, split by bounded context; models/__init__ re-exports (schema-neutral)
    closet.py  ingest.py  photo.py  products.py  stylist.py  chat.py  ranking.py  monetization.py  base.py
  db.py            # engine + SessionLocal ONLY; reads DB config from core.config (no raw os.getenv)
  platform/        # NEW neutral layer for cross-feature infra (breaks the cycles):
    ai_provider.py       # moved from services/ (consumed by gmail_closet, photo_closet, services)
    usage.py / costs.py  # moved from gmail_closet/ (shared cost accounting)
    jobs.py              # durable-job dispatch seam (queue-backed; wraps today's BackgroundTasks)
  providers/       # unified provider seams (Protocol + Null + factory + registry + enable flag)
    generation/  feed/  search/          # search/ ported to the gold-standard shape
  services/        # business logic; depends on core, models, platform, providers — never on api
    stylist/  tagging/  closet_service.py  enrichment.py  ...
  ingestion/       # gmail_closet + photo_closet regrouped; no longer import services top-level
  ranking/         # unchanged wall (import-linter enforced); depends down only
  monetization/    # unchanged wall
  api/             # thin routers ONLY: parse → call service → serialize. No inline ORM/business logic.
    routes/  (+ move main.py's handlers here: users.py, auth_legacy.py, outfit_upload.py)
  utils/           # true leaf: pure image/byte helpers; NO models/db imports (inject instead)
main.py            # wiring only: app factory, middleware, router includes, lifespan
```

**Layering rule (to lock with new import-linter contracts):**
`api → services → {platform, providers, models} → core`; `utils` and `core` are leaves; `ranking`/`monetization` stay walled; **no feature package imports `api`**, and `platform` breaks the `services ⇄ ingestion` cycles.

**Frontend target:** keep `ds/*` canonical; add `lib/api/http.ts` (one fetch wrapper: base URL from a single `config`, Bearer injection, typed error). Replace the two mock `*Client.ts` with real clients when endpoints land. `@tailor/contracts` stays the shared-type source; consider a contract test against the Python schemas.

---

## 16. Phased, independently-mergeable refactor plan

Each phase is behavior-preserving, small enough to review, and proven by the existing gates. **Phases are ordered but independently mergeable** unless noted.

| Phase | Scope | Files moved/changed | Risk | Regression proof |
|-------|-------|---------------------|------|------------------|
| **P3.1 Config centralization** | Route `db.py` + `supabase_storage.py` env reads through `Settings`; drop 2nd `load_dotenv`; add `pool_size`/`recycle`/CORS origins to config | `db.py`, `utils/supabase_storage.py`, `core/config.py`, `main.py` (CORS) | Low | pytest (DB/storage/config tests), app boot, alembic check |
| **P3.2 Split `models.py` → `models/` package** | Pure file move by context; `models/__init__` re-exports every name | `app/models.py` → `app/models/*`; imports unchanged (`from app.models import X` still works) | Low | pytest full suite (40+ importers), alembic **autogenerate no-op**, lint-imports |
| **P3.3 Break the cycles (platform layer)** | Move `ai_provider` + `usage`/`costs` into `app/platform/`; update imports; add import-linter contract forbidding `services ↔ ingestion` cycles | `services/ai_provider.py`, `gmail_closet/usage.py`, `stylist/costs.py`, importers | Med | pytest; new lint-imports contract goes green |
| **P3.4 Unify `SEARCH_PROVIDER` seam** | Port to Protocol + registry + factory + Null (mirror `GenerationProvider`); no behavior change (serper default) | `gmail_closet/shopping_search.py` → `providers/search/*` | Low-Med | pytest (search tests), golden search test |
| **P3.5 Thin `main.py`** | Move `/users`, `/signup`, `/login`, `/outfit-image` handlers into routers/services; **security decision on S1/S2 applied here** | `main.py` → `api/routes/{users,auth_legacy,outfit_upload}.py` | Med (touches auth) | pytest (auth/upload tests), manual auth smoke |
| **P3.6 Decompose `ai_provider.py` + hoist model strings** | Extract `chat()`/response-parse helpers; move hardcoded model names to `settings` | `services/ai_provider.py` (+`platform/` after P3.3) | Med | pytest (provider tests), bake-off unaffected |
| **P3.7 Decompose `image_resolver.py`** | Split cache / html-parse / scoring / resolve | `gmail_closet/image_resolver.py` | Med | pytest (resolver tests) |
| **P3.8 Durable jobs seam** | Introduce `platform/jobs.py`; make `gmail_ingest` resumable + strand-proof; unify dispatch idioms | ingest/photo/chat dispatch sites | High | pytest + integration; restart-mid-sync test |
| **P3.9 Dep cleanup** | Remove `openai`, `supabase`, `google-auth-oauthlib`, `email-validator`; bump `python-jose`; annotate ceiling pins | `requirements.txt` | Low-Med | pytest, fresh venv install, app boot |
| **P3.10 Frontend API-client consolidation** | Add `lib/api/http.ts`; migrate modules; single base-URL config | `apps/web/src/lib/api/*` | Low | tsc, vitest, next build |
| **P3.11 Scripts reorg + logging** | `scripts/ops/` vs `scripts/dev/`; shared logging bootstrap; structured logs + request-id middleware | `scripts/*`, `core/logging.py`, `main.py` | Low | pytest (imports), scripts smoke |
| **P3.12 Observability + limiter** | Move events rate-limiter to Postgres (like chat); PII log scrubber | `events.py`, logging | Low-Med | pytest (events tests) |

**Sequencing note:** P3.2 and P3.3 are the highest-leverage structural moves and should land early (they unblock everything). P3.5 and P3.8 carry the security/behavior weight — review carefully. P3.1, P3.9, P3.10, P3.11 are low-risk and can land anytime.

---

## 17. Appendix — Phase-2 changes, gates, stale branches

### 17a. Phase-2 executed on `chore/scale-housekeeping` (safe, reversible, behavior-preserving)

**Dead frontend source removed (13 files, all grep-proven zero production references):**
- `apps/web/src/app/login/page.tsx`, `apps/web/src/app/gmail-sync/page.tsx` — §9 orphaned redirect shims (0 in-app links; `next build` confirms routes gone).
- `apps/web/src/components/landing/FloatingClothes.tsx` — §9, whole `landing/` dir dead.
- `apps/web/src/components/closet/OutfitImageUpload.tsx` + `__tests__/OutfitImageUpload.test.tsx` — §9, superseded by `PhotoIngestUpload`.
- Cascade freed by the above: `components/ui/button.tsx`, `lib/api/outfit.ts`, `lib/api/outfit/index.ts` (dead+shadowed).
- Hard-dead shadcn scaffolding: `components/ui/badge.tsx`, `components/ui/input.tsx`, `components/ui/EmptyState.tsx`, `components/ui/LightButton.tsx`.
- Orphaned onboarding step: `components/onboarding/steps/_slider.tsx`.

**Tracked generated artifacts untracked (`git rm --cached`, kept on disk):** 4× `.DS_Store`, `.cursor/debug.log`, `bakeoff_out/*` (8), `outfit_outputs/*/summary.json` (3).

**`.gitignore`:** added `bakeoff_out/` (the others were already ignored; files predated the rules).

**Not touched (flagged only, behavior-bearing):** backend `/users`, `/users/{user_id}/clothing`, `/signup`, `/login` (S1/S2); `lib/auth/storage.ts` deprecated shim; `migrations/*.sql` legacy SQL; dependency removals (deferred to P3.9).

### 17b. Gate commands + results (run these to verify green)

| Gate | Command | Result on this branch |
|------|---------|----------------------|
| pytest | `LOCAL_DB=sqlite python -m pytest -q` (conftest sets `LOCAL_DB=sqlite`) | **489 passed, 1 skipped** |
| lint-imports | `lint-imports` | **2 contracts KEPT, 0 broken** |
| alembic | `alembic check` | **No new upgrade operations; head `0025`** |
| tsc | `npm run type-check --workspace=apps/web` (`tsc --noEmit`) | **0 errors** (after `next build` regenerated stale `.next/types`) |
| vitest | `npm run test --workspace=apps/web` (`vitest run`) | **16 files, 113 tests passed** |
| next build | `npm run build --workspace=apps/web` | **✓ compiled; `/login` + `/gmail-sync` absent** |

> tsc note: `tsconfig` globs `.next/types/**`. Deleting the two route pages left stale generated stubs that tsc flagged; a `next build` regenerates them and tsc is then clean. Run `next build` before `tsc` after any route deletion.

### 17c. Stale branches — delete commands (LISTED, not executed; do not delete remotes automatically)

**Local branches merged into `main` (safe to delete):**
```bash
# NOTE: claude/* are checked out in linked worktrees — remove the worktree first.
git worktree remove .claude/worktrees/loving-goldwasser-983628
git worktree remove .claude/worktrees/trusting-panini-911ff0
git branch -d claude/loving-goldwasser-983628 claude/trusting-panini-911ff0
git branch -d f2-feed-ranker redesign/ui-implementation
```
**Local unmerged (keep):** `polish/collage-lookbook` (collage work not yet merged — do NOT delete).

**Remote branches merged into `origin/main` (Guy runs these — not executed here):**
```bash
git push origin --delete Frontend_Edition
git push origin --delete phase1/frontend-auth-cutover
git push origin --delete recovery-backend-keep-fe-main
```

### 17d. Backup schemas (flagged for a separate DB task — DB not touched)

`backup_prerebuild` and `backup_pre_reconcile` have **no trace in the repo** (searched all `.py`/`.sql`/`.md`). If they exist, they were created out-of-band. `alembic/env.py:28-61` already excludes any `backup_*` table from autogenerate, so they won't trigger spurious drops. **Action (separate, operator-run):** verify their existence against the live DB and `DROP SCHEMA` if confirmed leftover — out of scope for this behavior-preserving pass and the "don't touch the DB" invariant.

---

*End of audit. Phase 3 structural work awaits review.*
