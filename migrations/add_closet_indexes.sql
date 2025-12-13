-- UP Migration: Add indexes for closet performance optimization
-- These indexes optimize GET /closet queries

-- Index for filtering clothing_items by user_id (most common query)
CREATE INDEX IF NOT EXISTS idx_clothing_items_user_id ON clothing_items(user_id);

-- Composite index for filtering by user_id and ordering by created_at DESC
CREATE INDEX IF NOT EXISTS idx_clothing_items_user_id_created_at ON clothing_items(user_id, created_at DESC);

-- Index for filtering item_images by clothing_item_id (for image URL lookup)
CREATE INDEX IF NOT EXISTS idx_item_images_clothing_item_id ON item_images(clothing_item_id);

-- Composite index for finding primary images efficiently
CREATE INDEX IF NOT EXISTS idx_item_images_clothing_item_id_is_primary ON item_images(clothing_item_id, is_primary) WHERE is_primary = true;

-- DOWN Migration (for rollback):
-- DROP INDEX IF EXISTS idx_clothing_items_user_id;
-- DROP INDEX IF EXISTS idx_clothing_items_user_id_created_at;
-- DROP INDEX IF EXISTS idx_item_images_clothing_item_id;
-- DROP INDEX IF EXISTS idx_item_images_clothing_item_id_is_primary;

