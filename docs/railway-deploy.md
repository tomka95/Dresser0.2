# Deploying the backend to Railway

Two always-on services, one repo, one Docker image; only the start command
differs. The web app (`apps/web`) stays on Vercel and is untouched — the
`.dockerignore` and `watchPatterns` keep it out of backend builds entirely.

| Service | Start command | Public? | Config file |
|---|---|---|---|
| `api` | `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips '*'` | yes (Generate Domain) | `railway.api.toml` |
| `worker` | `python -m app.worker` | **no** (no domain, no healthcheck) | `railway.worker.toml` |

DB: Supabase **Frankfurt** via the Supavisor **session pooler**
(`aws-0-eu-central-1.pooler.supabase.com:5432`, user `postgres.<project-ref>`) —
the same host/port shape already used in local dev. `sslmode=require` is
appended automatically when the `DB_*` parts are used
([app/db.py](../app/db.py) `_build_database_url`); if you switch to a single
`DATABASE_URL` instead, append `?sslmode=require` yourself.

## One-time setup

1. Railway → New Project → **Deploy from GitHub repo** (root directory stays the
   repo root). This becomes the **api** service.
2. api service → Settings → **Config-as-code** → path `railway.api.toml`.
3. Same project → **New Service → GitHub repo** (same repo) — the **worker**.
   Settings → Config-as-code → path `railway.worker.toml`.
4. Region: both TOMLs pin `europe-west4-drams3a` (Amsterdam, EU-West — closest
   to Frankfurt). If your plan/UI rejects the id, delete the `region` line and
   set it per service in the dashboard.
5. Variables: put the shared set (everything below marked `both`) in the
   project's **Shared Variables**, reference them from each service
   (`${{shared.VAR_NAME}}`), and add service-only ones (e.g.
   `CORS_ALLOWED_ORIGINS`) on the service.
6. api service → Settings → Networking → **Generate Domain** (or attach
   `api.<your-domain>`). Do **not** generate a domain for the worker.
7. Point the Vercel app's API base URL at the new api domain, and set
   `CORS_ALLOWED_ORIGINS` here to the Vercel origin(s).

Deploy gating: Railway health-checks `GET /health` (no auth, no DB round-trip —
[main.py](../main.py)) before cutting traffic to a new deploy. App startup runs
`check_database_connection()` first, so a deploy with broken DB config never
reports healthy and the previous deploy stays live.

## Migrations — never automatic

There is deliberately **no `preDeployCommand`**: `main` can carry migrations
that haven't been signed off / applied (current practice applies them to the
remote DB explicitly, ahead of merges). Keep doing that. If you ever want to
run one from the deploy environment: `railway run --service api alembic upgrade head`
(alembic + `alembic.ini` ship in the image and read the same `DB_*` env).

## u2net weights (item cutouts)

The ~176MB u2net model is deliberately **not** baked into the image
(`requirements.txt` note). On Railway's ephemeral disk it re-downloads to
`U2NET_HOME=/home/appuser/.u2net` on the **first matte after each deploy**
(background birth hook — adds ~30–60s there, once, not per request). If that
bothers you later: mount a Railway volume at `/home/appuser/.u2net` on each
service (watch volume file-ownership vs the non-root `appuser`), or uncomment
the bake line in the [Dockerfile](../Dockerfile).

## Durable-jobs flags — worker deploys inert (SCRUM-66)

`JOBS_GMAIL_INGEST_ENABLED` / `JOBS_PHOTO_GENERATION_ENABLED` default **false**
in code ([app/core/config.py](../app/core/config.py)). Leave them unset: the
api keeps its in-process BackgroundTasks dispatch, nothing enqueues, and the
worker just polls an empty queue every 2s (log shows
`worker <host>: starting (poll=2.0s stale=1800.0s)` then silence). When the
SCRUM-66 kill-test happens, flip each flag on **both** services (the api reads
it to decide enqueue-vs-inline; the worker processes whatever is enqueued).

## Scaling limits (SCRUM-67) — read before adding replicas

Two abuse guards are **in-process memory**:

* `POST /events` sliding window — [app/api/routes/events.py:53](../app/api/routes/events.py)
* monetization click/redirect window — [app/monetization/routes.py:39](../app/monetization/routes.py)

Chat/outfits/today's-look rate limits + the photo/chat quotas are already
Postgres-backed (`chat_rate_windows`, usage tables) and replica-safe. The two
above are per-process: with `--workers 1` on 1 replica they are now **exact**
(no ×2 ceiling). **Move them to Postgres/Redis before scaling either service
past 1 replica** or raising the worker count. Both TOMLs pin `numReplicas = 1`
for this reason.

Connection budget: SQLAlchemy pool is 5 + 10 overflow **per process** → api
(1 worker) + worker ≈ 30 connections peak, ~10 idle. Fine on the session
pooler; check Supabase → Database → Connection pooling if you raise anything.

## Env-var manifest

“Regenerate” = do not carry the dev value into prod. Generators:
state secrets `python -c "import secrets;print(secrets.token_urlsafe(48))"`;
enc key `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.

### Database (both services — required)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `DB_USER` | both | no | `postgres.<project-ref>` | Session-pooler username (Dashboard → Connect → Session pooler). |
| `DB_PASSWORD` | both | **yes** | — | Frankfurt DB password. Consider rotating (it has lived in a dev `.env`); rotating also breaks local dev until updated. |
| `DB_HOST` | both | no | `aws-0-eu-central-1.pooler.supabase.com` | Session pooler host (IPv4-safe; the direct `db.<ref>` host is IPv6-only). |
| `DB_PORT` | both | no | `5432` | Session mode. Don't switch to 6543 (transaction mode) casually. |
| `DB_NAME` | both | no | `postgres` | |

### Supabase auth + admin

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `SUPABASE_PROJECT_REF` | both | no | `<frankfurt-ref>` | Derives JWKS URL + issuer for ES256 verification. Unset ⇒ every authed request 401s (fail closed) while `/health` stays 200 — the app boots but is useless, so treat as required. |
| `SUPABASE_SERVICE_ROLE_KEY` | api | **yes** | — | Only used by `DELETE /account` (GoTrue admin erase). Frankfurt project's key. Worker doesn't need it. |
| `SUPABASE_URL` / `SUPABASE_JWKS_URL` / `SUPABASE_JWT_ISSUER` / `SUPABASE_JWT_AUDIENCE` | — | no | *omit* | Derived from the project ref; overrides only for non-standard setups. |

### Storage — S3 protocol (both services — required)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `SUPABASE_S3_ENDPOINT` | both | no | `https://<ref>.storage.supabase.co/storage/v1/s3` | Copy from Dashboard → Storage → S3 connection. |
| `SUPABASE_S3_ACCESS_KEY` | both | **yes** | — | **Mint NEW keys in the Frankfurt project** (Storage → S3 access keys) — the Sydney keys died with the old project and these are currently missing even from local `.env`. Photo confirm, cutouts, collages, chat photo-ingest, and account deletion all hard-require them. |
| `SUPABASE_S3_SECRET_KEY` | both | **yes** | — | Pairs with the access key above. |
| `SUPABASE_S3_BUCKET` | both | no | `<images-bucket>` | The public images bucket name. |
| `SUPABASE_PUBLIC_BASE_URL` | both | no | `https://<ref>.supabase.co/storage/v1/object/public` | Public URL = `{base}/{bucket}/{key}`. |

### CORS (api only)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | api | no | `https://<app>.vercel.app,https://www.<domain>` | Comma-separated **exact** origins. Unset ⇒ localhost-only default = prod web blocked (fails closed, not open). Never `*` (credentials mode). |

### LLM + image generation (both services)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `GEMINI_API_KEY` | both | **yes** | — | Detect / extract / verify / stylist / enrichment / embeddings. Issue a separate **prod** key (quota + rotation isolation from the dev key). |
| `BFL_API_KEY` | both | **yes** | — | FLUX.2 [pro] — rung 1 of the live generation + t2i ladders. Without it (and nano off) generation produces nothing and photo items strand `pending`. Prod key recommended. |
| `GENERATION_NANO_FALLBACK_ENABLED` | both | no | `false` | Explicit `false` (matches the code default): the on-cap nano rung ($0.134/img) is never invoked. |
| `LLM_PROVIDER` | both | no | `gemini` | Code default; set for explicitness. |
| `GENERATION_ENABLED` | — | no | *omit* | Leave unset: the live ladders name their rungs explicitly and bypass this flag; it gates only the legacy no-name dispatch. |
| `FAL_API_KEY` | — | yes | *omit* | Bake-off only (seedream). |
| `OPENAI_API_KEY` | — | yes | *omit* | Unused with `LLM_PROVIDER=gemini`. |

### Gmail connect + receipt ingest (both services)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `GMAIL_OAUTH_CLIENT_ID` | both | no | `<id>.apps.googleusercontent.com` | Dedicated `gmail.readonly` client. Add the prod redirect URI in Google Console (or create a separate prod client). |
| `GMAIL_OAUTH_CLIENT_SECRET` | both | **yes** | — | **Regenerate for prod** (rotate in Google Console, or separate prod client — the dev secret has lived in `.env`). |
| `GMAIL_OAUTH_REDIRECT_URI` | both | no | `https://<web-origin>/gmail/oauth/callback` | Must exactly match Google Console; points at the **Vercel web app**, which relays the code to the api. |
| `GMAIL_OAUTH_STATE_SECRET` | both | **yes** | — | **Regenerate for prod.** Stateless HMAC — rotating only voids in-flight consents (10-min TTL). |
| `GMAIL_TOKEN_ENC_KEY` | both | **yes** | — | AES-256 key for stored Gmail **and** Calendar tokens. Rotating orphans tokens already encrypted in the Frankfurt DB (users must reconnect). **Rotate NOW, while there are ~no beta users** — don't carry the dev value into prod. |
| `GMAIL_SEARCH_ENABLED` | both | no | `true` / `false` | Tier-5 shopping search (paid, per-run capped). Dev `.env` sets it — decide deliberately for prod. |
| `SERPER_API_KEY` | both | **yes** | — | Required iff `GMAIL_SEARCH_ENABLED=true`. Prod key recommended. |
| `SEARCH_PROVIDER` | both | no | `serper` | Code default. |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | — | yes | *omit* | Only for `SEARCH_PROVIDER=dataforseo`. |
| `GMAIL_MAX_YEARS` | both | no | `2` | Code default. |
| `GMAIL_VERIFY_ENABLED` / `GMAIL_TYPE_CLASSIFIER_ENABLED` | both | no | `true` | Code defaults; keep on. |

### Calendar connect (api)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `CALENDAR_OAUTH_CLIENT_ID` | api | no | `<id>.apps.googleusercontent.com` | Dedicated `calendar.events.readonly` client. |
| `CALENDAR_OAUTH_CLIENT_SECRET` | api | **yes** | — | **Regenerate for prod** (as with Gmail's). |
| `CALENDAR_OAUTH_REDIRECT_URI` | api | no | `https://<web-origin>/calendar/oauth/callback` | Must exactly match Google Console. |
| `CALENDAR_OAUTH_STATE_SECRET` | api | **yes** | — | **Regenerate for prod**; independent of the Gmail state secret on purpose. |
| `CALENDAR_ENABLED` | api | no | `true` | Code default. Token encryption reuses `GMAIL_TOKEN_ENC_KEY`. |

### Durable jobs (flags read by BOTH; tuning read by worker)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `JOBS_GMAIL_INGEST_ENABLED` | both | no | `false` | **Stays false / unset until SCRUM-66.** Flip on both services together. |
| `JOBS_PHOTO_GENERATION_ENABLED` | both | no | `false` | Same. |
| `JOBS_POLL_INTERVAL_SECONDS` / `JOBS_STALE_SECONDS` / `JOBS_MAX_ATTEMPTS` / `JOBS_RETRY_*` / `JOBS_WORKER_ID` | worker | no | *omit* | Code defaults are right; `JOBS_WORKER_ID` falls back to the container hostname. |

### Monetization (api — optional stubs)

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `SOVRN_SITE_ID` / `SKIMLINKS_PUBLISHER_ID` / `SHEIN_AFFILIATE_ID` / `ALIEXPRESS_AFFILIATE_ID` | api | yes | *omit* | Unset ⇒ `/out` returns plain product URLs. NOTE: `SOVRN_API_KEY` / `SOVRN_SECRET_KEY` in the local `.env` are **not read by the backend** (no such settings) — dead entries, don't copy them over. |

### Injected / must-NOT-set

| Var | Service(s) | Secret? | Example / placeholder | Notes |
|---|---|---|---|---|
| `PORT` | api | — | *Railway-injected* | uvicorn binds it; never set manually. |
| `LOCAL_DB` / `USE_SQLITE` | — | — | **NEVER SET** | Would silently swap the prod DB for an ephemeral in-container SQLite (only a log warning). The one true silent footgun in config. |
| `ALLOW_REMOTE_TEST_DB` | — | — | never | pytest escape hatch only. |
| `GMAIL_DEV_SCAN_CAP_ENABLED` (+ `GMAIL_DEV_SCAN_MAX_*`) | — | — | **omit in prod** | Dev-only scan cap; it IS set in the local dev `.env` — do not copy. |

Everything else in [app/core/config.py](../app/core/config.py) (model names,
quotas `CHAT_*` / `PHOTO_MONTHLY_QUOTA`, `RANKING_*`, `DISTILL_*`,
`ENRICHMENT_*`, per-unit cost rates, `WEATHER_*` — weather is keyless and on by
default) has a deliberate code default; override only when you mean to change
product behavior.

### Secrets checklist for prod

* **Mint new (don't exist yet):** `SUPABASE_S3_ACCESS_KEY` + `SUPABASE_S3_SECRET_KEY` (Frankfurt).
* **Regenerate (never carry dev values):** `GMAIL_OAUTH_STATE_SECRET`,
  `CALENDAR_OAUTH_STATE_SECRET`, `GMAIL_TOKEN_ENC_KEY` (pre-beta, accepts
  reconnects), `GMAIL_OAUTH_CLIENT_SECRET`, `CALENDAR_OAUTH_CLIENT_SECRET`.
* **Fresh prod keys recommended:** `GEMINI_API_KEY`, `BFL_API_KEY`,
  `SERPER_API_KEY`.
* **Frankfurt-native (already prod-grade, rotate at your discretion):**
  `DB_PASSWORD`, `SUPABASE_SERVICE_ROLE_KEY`.
