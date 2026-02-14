-- Backfill slugs for all works that don't have one yet.
-- Format: {type_code_lowercase}-{number_sanitized}-{year}
-- Sanitize: replace / with -, lowercase
-- UUD works already have custom slugs — protected by WHERE slug IS NULL.

UPDATE works
SET slug = LOWER(rt.code) || '-' || LOWER(REPLACE(works.number, '/', '-')) || '-' || works.year::text
FROM regulation_types rt
WHERE works.regulation_type_id = rt.id
  AND works.slug IS NULL;

-- Ensure uniqueness by adding an index if not already present
CREATE UNIQUE INDEX IF NOT EXISTS idx_works_slug_unique ON works (slug) WHERE slug IS NOT NULL;
