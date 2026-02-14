-- Migration 033: Add 'tentang' (subject/about) column to works.
-- Extracted from peraturan.go.id detail page metadata table.
ALTER TABLE works ADD COLUMN IF NOT EXISTS tentang TEXT;
