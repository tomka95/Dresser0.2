-- UP Migration: Add gmail_sync_completed_at column to users table
ALTER TABLE users 
ADD COLUMN gmail_sync_completed_at TIMESTAMP WITH TIME ZONE NULL;

-- DOWN Migration (for rollback):
-- ALTER TABLE users 
-- DROP COLUMN IF EXISTS gmail_sync_completed_at;

