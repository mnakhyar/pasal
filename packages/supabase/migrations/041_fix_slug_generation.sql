-- Migration 041: Fix slug generation to include issuer from frbr_uri
--
-- Problem: slugs are generated as {code}-{number}-{year} (e.g. "perda-1-2023")
-- but multiple issuers can share code+number+year:
--   PERDA Kota Depok No. 1/2023 → perda-1-2023
--   PERDA Kab. Bengkulu Utara No. 1/2023 → perda-1-2023 (collision!)
--
-- The frbr_uri already encodes the issuer in the 4th segment:
--   /akn/id/act/perda-kabupaten-pati/2023/1
--   /akn/id/act/permen-esdm/2026/2
--   /akn/id/act/uu/2003/13
--
-- Fix: extract the type-prefix from frbr_uri for the slug, falling back to
-- the regulation_type code when frbr_uri is unavailable.

-- 1. Drop the old unique index (we'll recreate after regenerating slugs)
DROP INDEX IF EXISTS idx_works_slug_unique;

-- 2. Update the trigger function to use frbr_uri prefix
CREATE OR REPLACE FUNCTION generate_work_slug()
RETURNS TRIGGER AS $$
DECLARE
    type_prefix TEXT;
BEGIN
    IF NEW.slug IS NULL THEN
        -- Extract issuer-aware prefix from frbr_uri if available
        -- e.g. /akn/id/act/perda-kabupaten-pati/2023/1 → "perda-kabupaten-pati"
        IF NEW.frbr_uri IS NOT NULL AND NEW.frbr_uri LIKE '/akn/%' THEN
            type_prefix := split_part(NEW.frbr_uri, '/', 5);
        END IF;

        -- Fallback to regulation_type code if frbr_uri doesn't yield a prefix
        IF type_prefix IS NULL OR type_prefix = '' THEN
            SELECT LOWER(rt.code)
            INTO type_prefix
            FROM regulation_types rt
            WHERE rt.id = NEW.regulation_type_id;
        END IF;

        NEW.slug := LOWER(type_prefix)
            || '-' || LOWER(REPLACE(NEW.number, '/', '-'))
            || '-' || NEW.year::text;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Regenerate ALL slugs using the new logic (direct UPDATE, trigger is INSERT-only)
UPDATE works
SET slug = COALESCE(
    CASE
        WHEN frbr_uri IS NOT NULL AND frbr_uri LIKE '/akn/%'
        THEN LOWER(split_part(frbr_uri, '/', 5))
            || '-' || LOWER(REPLACE(number, '/', '-'))
            || '-' || year::text
        ELSE NULL
    END,
    LOWER(rt.code) || '-' || LOWER(REPLACE(works.number, '/', '-')) || '-' || works.year::text
)
FROM regulation_types rt
WHERE works.regulation_type_id = rt.id;

-- 4. Recreate unique index
CREATE UNIQUE INDEX idx_works_slug_unique ON works (slug) WHERE slug IS NOT NULL;

-- 5. Reset slug-collision failures to pending for reprocessing
-- These failed with "Failed to upsert work" due to the old slug generation
UPDATE crawl_jobs
SET status = 'pending',
    error_message = NULL,
    updated_at = NOW()
WHERE status = 'failed'
  AND error_message LIKE 'Failed to upsert work%';
