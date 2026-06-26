# Tailor - AI Closet / Stylist App

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your OpenAI API key:
   
   **Option 1: Using a .env file (Recommended)**
   
   Create a `.env` file in the project root:
   ```
   OPENAI_API_KEY=your-api-key-here
   ```
   
   The code will automatically load this file using `python-dotenv`.
   
   **Option 2: Environment variable**
   ```bash
   # Windows PowerShell
   $env:OPENAI_API_KEY="your-api-key-here"
   
   # Linux/Mac
   export OPENAI_API_KEY="your-api-key-here"
   ```

3. Place a test outfit image at `Images/test_outfit.jpg`

## Database & Schema Migrations

The PostgreSQL database (Supabase) is the system of record. Its schema is owned
**exclusively by versioned Alembic migrations** in `alembic/`. The application
never creates or alters schema at startup — it only verifies the configured
database is reachable and fails loudly otherwise.

### How a schema change happens

1. Edit the ORM models in `app/models.py`.
2. Generate a migration:
   ```bash
   alembic revision --autogenerate -m "describe the change"
   ```
3. Review the generated migration in `alembic/versions/` (always read it).
4. Apply it:
   ```bash
   alembic upgrade head
   ```

`alembic/versions/0001_baseline_live_schema.py` is the baseline — it reflects the
schema that already exists in production. For the existing live database, record
the baseline **once** without running DDL:
```bash
alembic stamp 0001_baseline
```

### Database configuration & connection behavior

Connection config comes from environment variables / `.env` only:

- `DATABASE_URL` (preferred), **or** all of `DB_USER`, `DB_PASSWORD`, `DB_HOST`,
  `DB_NAME` (optional `DB_PORT`, default 5432).

If the database is **misconfigured or unreachable, the app fails loudly** with an
actionable error. It will **never** silently fall back to a local/empty database.

To develop locally without the production database, opt in **explicitly**:

```bash
LOCAL_DB=sqlite     # use a local SQLite file (tailor.db)
LOCAL_DB=postgres   # use a local Postgres at localhost:5432/tailor
# USE_SQLITE=1 is a convenience alias for LOCAL_DB=sqlite
```

The Alembic baseline is Postgres-specific (jsonb, text[], GIN indexes). For local
schema in `LOCAL_DB=postgres`, run `alembic upgrade head`. The `LOCAL_DB=sqlite`
mode is intended for app-boot / non-Postgres-specific development; the test suite
uses it and builds its schema from the ORM models directly.

## Running the Integration Test

Run the full pipeline test:
```bash
pytest tests/integration/test_clothing_pipeline.py -v
```

The test will:
- Detect all clothing items in the outfit image
- Generate product-style images for each item
- Get brand/store metadata for each item
- Save results to the `Responses/` folder:
  - Individual product images (PNG files)
  - `items_summary.json` - Complete JSON summary
  - `items_summary.txt` - Human-readable text summary

## Project Structure

```
Tailor0.2/
├── app/
│   ├── services/
│   │   └── clothing_pipeline.py  # Main pipeline service
├── tests/
│   └── integration/
│       └── test_clothing_pipeline.py  # Integration test
├── Images/  # Place test outfit images here
├── Responses/  # Generated images and summaries go here
└── requirements.txt
```

## Note on Model Names

The code uses `gpt-4o-mini` for vision tasks and `dall-e-3` for image generation, which are the current OpenAI models. If you need to use different model names, update them in `app/services/clothing_pipeline.py`.

