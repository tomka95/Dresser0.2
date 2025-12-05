# Contract & API Notes

This file tracks contract and API TODOs for the backend engineer. When frontend development identifies a need for a new API endpoint, database schema change, or contract modification that hasn't been implemented yet, it should be documented here.

## Closet

- [Closet] GET /api/closet (list) + POST /api/closet (create) to replace the mock list/add functions.
- [Closet] Image upload endpoint for ClosetItem images.
- [Closet] Filtering/search endpoints for ClosetItem (category, color, brand query params).

## Outfits

- [Outfits] POST /api/outfits/suggest returning `OutfitSuggestion[]` (including `recommendedItems[]` with `{ id, name, reason }` for “add 1 new item” use cases).
- [Outfits] Endpoints for saving/favoriting suggestions (e.g., POST /api/outfits and DELETE /api/outfits/:id/favorite).
- [Outfits] GET /api/outfits/history to retrieve a user’s previously generated outfits.

## User Profile

- [User] API endpoints for user profile management (GET/PUT /api/user).
- [User] Authentication endpoints (sign up, sign in, sign out) via Supabase Auth.
- [User] User preferences/settings endpoints (style preferences, sizing, etc.).

## Analytics

The frontend tracks user interactions and page views. Current implementation logs to console; Mixpanel integration pending.

### Events Tracked

- `closet_viewed` - Fires when closet page is viewed. Props: `{ item_count: number }`
- `closet_items_loaded` - Fires after successful fetch. Props: `{ count: number, categories: string[] }`
- `closet_item_added` - Fires when user successfully adds an item. Props: `{ category: string, has_image: boolean, has_brand: boolean, total_items: number }`
- `closet_item_add_failed` - Fires when item addition fails. Props: `{ error: string }`
- `outfit_suggestions_viewed` - Fires when outfits page is viewed. Props: `{ outfit_count: number, has_recommended_items: boolean }`
- `outfit_suggestions_loaded` - Fires after successful fetch. Props: `{ count: number, has_recommended_items: boolean, total_recommended_items: number }`
- `outfit_liked` - Fires when user likes an outfit. Props: `{ outfit_id: string, has_recommended_items: boolean, occasion?: string }`
- `outfit_unliked` - Fires when user unlikes an outfit. Props: `{ outfit_id: string, has_recommended_items: boolean, occasion?: string }`
- `outfit_regenerate_clicked` - Fires when user clicks "Generate Outfit" button
- `outfit_regenerate_failed` - Fires when regenerate fails. Props: `{ error: string }`

