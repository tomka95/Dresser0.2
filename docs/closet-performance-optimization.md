# Closet Performance Optimization - Implementation Report

## Changes Made

### 1. Added Performance Timing Logs

**File:** `app/api/routes/closet.py`

Added timing logs with `[CLOSET_PERF]` prefix in `list_closet_items_endpoint()`:
- Total request time
- DB query time
- Mapping/serialization time
- Item count

**Example log output:**
```
[CLOSET_PERF] GET /closet - total=45.23ms, db_query=12.45ms, mapping=2.18ms, items_count=15
```

### 2. Fixed N+1 Query Issue

**Problem Identified:**
- `_get_image_url()` was making a separate DB query for each item that didn't have `image_url` set
- For 10 items without `image_url`, this resulted in 11 queries (1 for items + 10 for images)

**Solution Implemented:**
- **File:** `app/services/closet_service.py`
  - Added `selectinload(ClothingItem.images)` to eagerly load all ItemImage relationships in a single query
  - This reduces N queries to 2 queries total (1 for items + 1 for all images)

- **File:** `app/api/routes/closet.py`
  - Updated `_get_image_url()` to accept `item` only (no `db` parameter)
  - Changed logic to use in-memory `item.images` list instead of DB query
  - Updated `_map_clothing_item_to_out()` to not require `db` parameter

**Query Strategy:**
- **Before:** 1 query for items + N queries for images (N+1 problem)
- **After:** 1 query for items + 1 query for all images (2 queries total)
- Uses SQLAlchemy `selectinload()` which generates: `SELECT * FROM item_images WHERE clothing_item_id IN (...)` in a single query

### 3. Added Database Indexes

**File:** `app/models.py`

Added indexes to SQLAlchemy models:
- `ClothingItem.user_id` - Index on `user_id` column (for filtering)
- Composite index on `(user_id, created_at DESC)` - For filtering + ordering
- `ItemImage.clothing_item_id` - Index on foreign key
- Composite index on `(clothing_item_id, is_primary)` - For finding primary images

**Migration File:** `migrations/add_closet_indexes.sql`

**Indexes Created:**
1. `idx_clothing_items_user_id` - Single column index on `user_id`
2. `idx_clothing_items_user_id_created_at` - Composite index for filtering + ordering
3. `idx_item_images_clothing_item_id` - Foreign key index
4. `idx_item_images_clothing_item_id_is_primary` - Partial index (WHERE is_primary = true) for primary image lookups

**SQL Generated:**
```sql
CREATE INDEX idx_clothing_items_user_id ON clothing_items(user_id);
CREATE INDEX idx_clothing_items_user_id_created_at ON clothing_items(user_id, created_at DESC);
CREATE INDEX idx_item_images_clothing_item_id ON item_images(clothing_item_id);
CREATE INDEX idx_item_images_clothing_item_id_is_primary ON item_images(clothing_item_id, is_primary) WHERE is_primary = true;
```

### 4. Performance Tests

**File:** `tests/test_closet_performance.py`

Added performance regression tests:
- `test_get_closet_performance_with_many_items` - Benchmarks 20 items
- `test_get_closet_query_count` - Verifies no N+1 queries (10 items with ItemImages)

## Files Changed

### Modified Files
1. **`app/api/routes/closet.py`**
   - Added timing logs with `[CLOSET_PERF]` prefix
   - Removed `db` parameter from `_get_image_url()` and `_map_clothing_item_to_out()`
   - Updated to use in-memory `item.images` list

2. **`app/services/closet_service.py`**
   - Added `selectinload(ClothingItem.images)` to `list_closet_items()`
   - Eagerly loads all images in one query

3. **`app/models.py`**
   - Added `__table_args__` with Index definitions to `ClothingItem`
   - Added `__table_args__` with Index definitions to `ItemImage`
   - Added `index=True` to `user_id` and `clothing_item_id` columns

### New Files
1. **`migrations/add_closet_indexes.sql`** - SQL migration for indexes
2. **`tests/test_closet_performance.py`** - Performance test suite
3. **`docs/closet-performance-optimization.md`** - This document

## Query Optimization Details

### Before Optimization
```python
# GET /closet with 10 items (5 without image_url)
# Query 1: SELECT * FROM clothing_items WHERE user_id = ? ORDER BY created_at DESC
# Query 2: SELECT * FROM item_images WHERE clothing_item_id = ? AND is_primary = true  # Item 1
# Query 3: SELECT * FROM item_images WHERE clothing_item_id = ? AND is_primary = true  # Item 2
# ... (8 more queries)
# Total: 11 queries
```

### After Optimization
```python
# GET /closet with 10 items (5 without image_url)
# Query 1: SELECT * FROM clothing_items WHERE user_id = ? ORDER BY created_at DESC
# Query 2: SELECT * FROM item_images WHERE clothing_item_id IN (?, ?, ?, ...)  # All items
# Total: 2 queries
```

**SQLAlchemy selectinload generates:**
```sql
SELECT item_images.* 
FROM item_images 
WHERE item_images.clothing_item_id IN (uuid1, uuid2, uuid3, ...)
```

## Expected Performance Improvements

### Before
- **10 items:** ~11 DB queries, ~50-100ms (depending on DB latency)
- **50 items:** ~51 DB queries, ~250-500ms
- **100 items:** ~101 DB queries, ~500-1000ms

### After
- **10 items:** 2 DB queries, ~15-30ms
- **50 items:** 2 DB queries, ~20-40ms
- **100 items:** 2 DB queries, ~25-50ms

**Improvement:** ~10-20x reduction in query count, ~5-10x reduction in latency for large item counts.

## How to Apply Migration

```bash
# Connect to your database and run:
psql -d tailor -f migrations/add_closet_indexes.sql

# Or if using a different database client:
# Copy the UP migration SQL and execute it
```

## How to Run Performance Tests

```bash
# Run performance tests
pytest tests/test_closet_performance.py -v

# Run with timing output
pytest tests/test_closet_performance.py -v -s
```

## Monitoring Performance

After deployment, check server logs for `[CLOSET_PERF]` entries:
```
[CLOSET_PERF] GET /closet - total=45.23ms, db_query=12.45ms, mapping=2.18ms, items_count=15
```

**Expected ranges (local dev):**
- `db_query`: 10-50ms (depends on DB location and item count)
- `mapping`: 1-5ms (depends on item count)
- `total`: 15-60ms (includes FastAPI overhead)

## Rollback Plan

1. **Revert code changes:**
   - Remove `selectinload()` from `app/services/closet_service.py`
   - Restore `db` parameter to `_get_image_url()` and `_map_clothing_item_to_out()`
   - Remove timing logs from `app/api/routes/closet.py`
   - Remove indexes from `app/models.py`

2. **Revert database:**
   ```sql
   -- Run DOWN migration
   DROP INDEX IF EXISTS idx_clothing_items_user_id;
   DROP INDEX IF EXISTS idx_clothing_items_user_id_created_at;
   DROP INDEX IF EXISTS idx_item_images_clothing_item_id;
   DROP INDEX IF EXISTS idx_item_images_clothing_item_id_is_primary;
   ```

3. **Remove test file:**
   - Delete `tests/test_closet_performance.py`

## Verification

After applying changes, verify:
1. ✅ GET /closet returns same response structure (camelCase)
2. ✅ No N+1 queries (check logs or use query profiler)
3. ✅ Indexes exist in database (`\d+ clothing_items` and `\d+ item_images` in psql)
4. ✅ Performance tests pass
5. ✅ Timing logs appear in server output

