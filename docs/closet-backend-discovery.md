# Closet Backend Integration - Discovery Report

## 1. FastAPI Route Structure

### Router Registration Location
**File:** `main.py` (lines 54-61)

Routers are registered using `app.include_router()`:
```python
# Gmail clothing extraction endpoints (for Tailor MVP)
app.include_router(gmail_router)  # prefix="/api/v1/gmail"

# Authentication endpoints
app.include_router(auth_google.router)  # prefix="/auth"

# Gmail API endpoints (requires authentication)
app.include_router(gmail.router)  # prefix="/gmail"
```

### Router File Location
**Directory:** `app/api/routes/`
- `auth_google.py` - Authentication router (prefix="/auth")
- `gmail.py` - Gmail API router (prefix="/gmail")

**Proposed location for closet router:** `app/api/routes/closet.py`

### Authentication Dependency
**File:** `app/dependencies.py` (lines 24-64)

**Function:** `get_current_user()`
- Uses `HTTPBearer` security scheme
- Extracts JWT from `Authorization: Bearer <token>` header
- Decodes JWT using `settings.JWT_SECRET_KEY` and `settings.JWT_ALGORITHM`
- Returns `User` SQLAlchemy model instance
- Raises `HTTPException(401)` if invalid/missing token

**Usage pattern:**
```python
from app.dependencies import get_db, get_current_user
from app.models import User

@router.get("/endpoint")
async def my_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # current_user.id is the authenticated user's UUID
    pass
```

### Router Prefix Pattern
Existing routers use:
- `/auth` - Authentication endpoints
- `/gmail` - Gmail API endpoints (authenticated)
- `/api/v1/gmail` - Legacy Gmail router (not authenticated)

**Proposed prefix:** `/closet` (matches frontend expectation from `closetClient.ts`)

---

## 2. SQLAlchemy Models

### ClothingItem Model
**File:** `app/models.py` (lines 58-94)

**Table:** `clothing_items`

**Fields:**
- `id` (UUID, primary key)
- `user_id` (UUID, ForeignKey to users.id, NOT NULL)
- `name` (String, NOT NULL)
- `category` (String, nullable)
- `sub_category` (String, nullable)
- `color_primary` (String, nullable)
- `color_secondary` (String, nullable)
- `brand` (String, nullable)
- `size` (String, nullable)
- `image_url` (Text, nullable) - Direct URL field
- `created_at` (DateTime, default=datetime.utcnow)
- `updated_at` (DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

**Relationships:**
- `user` - relationship to User (back_populates="clothing_items")
- `images` - relationship to ItemImage[] (cascade="all, delete-orphan")
- `tags` - many-to-many relationship to Tag[] via `clothing_item_tags` table

### ItemImage Model
**File:** `app/models.py` (lines 98-118)

**Table:** `item_images`

**Fields:**
- `id` (UUID, primary key)
- `clothing_item_id` (UUID, ForeignKey to clothing_items.id, NOT NULL)
- `image_url` (Text, NOT NULL)
- `type` (String, nullable) - e.g., "email"
- `is_primary` (Boolean, default=False)
- `created_at` (DateTime, default=datetime.utcnow)

**Relationship:**
- `clothing_item` - relationship to ClothingItem (back_populates="images")

### Image URL Storage Pattern
**File:** `app/services/outfit_db_service.py` (lines 45-64)

Images are stored in Supabase Storage and the public URL is saved directly to `ClothingItem.image_url`:
```python
image_url = storage_client.upload_file(
    local_path=image_path,
    folder=str(user_id),
    content_type="image/png",
)
item.image_url = image_url  # Full public URL stored directly
```

**Note:** `image_url` in `ClothingItem` is a full public URL, not a path. The `ItemImage` table exists for multiple images per item, but the primary image is also stored in `ClothingItem.image_url`.

### Existing CRUD Patterns
**File:** `app/services/outfit_db_service.py` (lines 15-89)

**Pattern:** Service function that takes `db: Session`, `user_id: UUID`, performs operations, commits, returns dicts:
```python
def save_outfit_results_to_db(
    db: Session,
    user_id: UUID,
    results: List[Any],
    storage_client: SupabaseStorageClient,
) -> List[Dict[str, Any]]:
    # Create items
    # Commit
    # Return list of dicts
```

**File:** `app/services/email_clothing_service.py` (lines 12-178)

**Pattern:** Service function for saving email items with deduplication:
```python
def save_email_items_for_user(
    db: Session,
    user_id: UUID,
    items: Iterable[Union[dict, object]],
) -> List[ClothingItem]:
    # Deduplicate by (name, brand) case-insensitive
    # Create ClothingItem + ItemImage if image_url exists
    # Commit
    # Return List[ClothingItem]
```

---

## 3. Frontend API Abstraction

### Function Signatures
**File:** `apps/web/src/lib/api/closet/index.ts` (lines 19-27)

```typescript
export async function listClosetItems(): Promise<ClosetItem[]>
export async function addClosetItem(
  input: Omit<ClosetItem, 'id' | 'userId' | 'createdAt' | 'updatedAt'>
): Promise<ClosetItem>
```

### Expected Response Shape
**File:** `packages/contracts/src/closet.ts` (lines 6-18)

**ClosetItem Type:**
```typescript
{
  id: string;              // UUID
  userId: string;          // UUID
  name: string;            // min 1 char
  category?: 'top' | 'bottom' | 'dress' | 'outerwear' | 'shoes' | 'accessories' | 'other';
  color?: string;
  brand?: string;
  imageUrl?: string;       // URL (optional)
  createdAt: string;       // ISO datetime string
  updatedAt: string;       // ISO datetime string
}
```

### Store Usage
**File:** `apps/web/src/stores/useClosetStore.ts` (lines 27-47, 48-66)

- `fetchItems()` calls `apiListClosetItems()` and expects `ClosetItem[]`
- `addItem(input)` calls `apiAddClosetItem(input)` and expects single `ClosetItem` back
- Store handles loading/error states internally

---

## 4. HTTP Client Wrapper

### Current Pattern
**File:** `apps/web/src/lib/api/gmail/index.ts` (lines 23-65)

**Pattern:**
1. Get token from `localStorage.getItem('accessToken')`
2. Use native `fetch()` (no axios)
3. Attach token in `Authorization: Bearer <token>` header
4. Handle FastAPI error format (422 validation errors, error.detail)
5. Base URL: `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'`

**Example:**
```typescript
const token = localStorage.getItem('accessToken');
if (!token) {
  throw new Error('Not authenticated. Please sign in first.');
}

const response = await fetch(`${API_BASE_URL}/gmail/clothing-items`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  },
});

if (!response.ok) {
  const error = await response.json();
  // Handle FastAPI validation errors (422)
  if (Array.isArray(error.detail)) {
    const messages = error.detail.map((err: any) => err.msg).join(', ');
    throw new Error(messages);
  }
  throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed...');
}

return response.json();
```

---

## 5. Similar Existing Endpoints

### Authenticated List Endpoint
**File:** `app/api/routes/gmail.py` (lines 29-141)

**Endpoint:** `GET /gmail/messages`
- Uses `current_user: User = Depends(get_current_user)`
- Uses `db: Session = Depends(get_db)`
- Returns `List[Dict[str, Any]]`
- Filters by `current_user.id` implicitly (via GoogleAccount relationship)

### Authenticated Create Endpoint
**File:** `app/api/routes/gmail.py` (lines 144-215)

**Endpoint:** `POST /gmail/clothing-items`
- Uses `current_user: User = Depends(get_current_user)`
- Uses `db: Session = Depends(get_db)`
- Calls service function `save_email_items_for_user(db, current_user.id, items)`
- Returns `Dict[str, Any]` with `connected`, `items`, `saved_count`

### Legacy Create Endpoint (No Auth)
**File:** `main.py` (lines 86-108)

**Endpoint:** `POST /users/{user_id}/clothing`
- Takes `user_id` in path (NOT authenticated)
- Creates `ClothingItem` directly
- Returns minimal `{"id": str, "name": str}`

**Note:** This is a legacy endpoint. New endpoints should use `get_current_user` instead.

---

## 6. Proposed Implementation

### Endpoint Paths
Based on existing patterns:
- **GET** `/closet` - List user's clothing items
- **POST** `/closet` - Create new clothing item

**Rationale:**
- Matches frontend expectation (no `/api` prefix needed, unlike legacy `/api/v1/gmail`)
- Consistent with `/gmail` router pattern
- Simple, RESTful paths

### Router File
**File:** `app/api/routes/closet.py`

**Structure:**
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.models import User, ClothingItem

router = APIRouter(
    prefix="/closet",
    tags=["closet"],
)

@router.get("")
async def list_closet_items(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    # Query ClothingItem.filter(ClothingItem.user_id == current_user.id)
    # Return list matching ClosetItem contract
    pass

@router.post("")
async def create_closet_item(
    # Request body matching ClosetItem input (without id, userId, timestamps)
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Create ClothingItem with current_user.id
    # Return single item matching ClosetItem contract
    pass
```

### Registration in main.py
Add after line 61:
```python
from app.api.routes import closet

app.include_router(closet.router)
```

### Expected JSON Response Shape

**GET /closet:**
```json
[
  {
    "id": "uuid-string",
    "userId": "uuid-string",
    "name": "White Crew Tee",
    "category": "top",
    "color": "white",
    "brand": "Everlane",
    "imageUrl": "https://...",
    "createdAt": "2024-05-01T10:00:00.000Z",
    "updatedAt": "2024-05-01T10:00:00.000Z"
  },
  ...
]
```

**POST /closet:**
```json
{
  "id": "uuid-string",
  "userId": "uuid-string",
  "name": "New Item",
  "category": "top",
  "color": "blue",
  "brand": "Brand Name",
  "imageUrl": "https://...",
  "createdAt": "2024-05-01T10:00:00.000Z",
  "updatedAt": "2024-05-01T10:00:00.000Z"
}
```

### Field Mapping: DB → Frontend

| Database Field | Frontend Field | Notes |
|---------------|----------------|-------|
| `id` | `id` | Convert UUID to string |
| `user_id` | `userId` | Convert UUID to string, camelCase |
| `name` | `name` | Direct |
| `category` | `category` | Direct (may need validation against enum) |
| `color_primary` | `color` | Use primary, fallback to secondary |
| `brand` | `brand` | Direct |
| `image_url` | `imageUrl` | Direct, camelCase |
| `created_at` | `createdAt` | Convert DateTime to ISO string, camelCase |
| `updated_at` | `updatedAt` | Convert DateTime to ISO string, camelCase |

**Note:** Frontend expects `color` (singular), DB has `color_primary` and `color_secondary`. Use `color_primary` or combine both.

### Frontend API Client Update
**File:** `apps/web/src/lib/api/closet/index.ts`

Replace mock calls with:
```typescript
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function listClosetItems(): Promise<ClosetItem[]> {
  const token = localStorage.getItem('accessToken');
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/closet`, {
    method: 'GET',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((err: any) => err.msg).join(', ');
      throw new Error(messages);
    }
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to load closet items');
  }

  return response.json();
}

export async function addClosetItem(
  input: Omit<ClosetItem, 'id' | 'userId' | 'createdAt' | 'updatedAt'>
): Promise<ClosetItem> {
  const token = localStorage.getItem('accessToken');
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/closet`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const error = await response.json();
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((err: any) => err.msg).join(', ');
      throw new Error(messages);
    }
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to add closet item');
  }

  return response.json();
}
```

---

## Summary

- **Router location:** `app/api/routes/closet.py` with prefix `/closet`
- **Registration:** Add `app.include_router(closet.router)` in `main.py` after line 61
- **Auth:** Use `current_user: User = Depends(get_current_user)` pattern
- **DB query:** Filter by `ClothingItem.user_id == current_user.id`
- **Response format:** Match `ClosetItem` contract from `@tailor/contracts`
- **Frontend update:** Replace mock in `apps/web/src/lib/api/closet/index.ts` with fetch calls to `/closet`
- **Field mapping:** Map DB snake_case to frontend camelCase, combine color fields

