-- Migration 040: Add no_pdf and needs_ocr statuses to crawl_jobs
--
-- Problem: 18,739 jobs are marked 'failed' but the source simply has no PDF.
-- Another 916 are scanned-image PDFs with no text layer. These pollute the
-- real failure count and make actual bugs hard to find.
--
-- This migration:
-- 1. Expands the CHECK constraint to allow 'no_pdf' and 'needs_ocr'
-- 2. Reclassifies existing failures into the correct status
-- 3. Resets 'downloaded' stuck jobs to 'pending'
-- 4. Adds indexes for new statuses

-- 1. Drop the existing CHECK constraint and add a new one with expanded statuses
ALTER TABLE crawl_jobs DROP CONSTRAINT IF EXISTS crawl_jobs_status_check;
ALTER TABLE crawl_jobs ADD CONSTRAINT crawl_jobs_status_check
    CHECK (status IN ('pending', 'crawling', 'downloaded', 'parsed', 'loaded', 'failed', 'no_pdf', 'needs_ocr'));

-- 2. Reclassify "No PDF URL found" failures → no_pdf
-- These are regulations where the source page exists but has no downloadable PDF.
UPDATE crawl_jobs
SET status = 'no_pdf',
    updated_at = NOW()
WHERE status = 'failed'
  AND error_message LIKE 'No PDF URL found%';

-- Also catch the variant from _extract_pdf_url_from_detail_page
UPDATE crawl_jobs
SET status = 'no_pdf',
    updated_at = NOW()
WHERE status = 'failed'
  AND error_message LIKE '%page loaded but no PDF link in HTML%';

-- 3. Reclassify "PDF text too short" failures → needs_ocr
-- These are scanned-image PDFs where PyMuPDF extracts <100 chars.
UPDATE crawl_jobs
SET status = 'needs_ocr',
    updated_at = NOW()
WHERE status = 'failed'
  AND error_message LIKE 'PDF text too short%';

-- 4. Reset stuck 'downloaded' jobs to 'pending' for reprocessing
UPDATE crawl_jobs
SET status = 'pending',
    updated_at = NOW()
WHERE status = 'downloaded';

-- 5. Add partial indexes for the new statuses (used in dashboard counts and queries)
CREATE INDEX IF NOT EXISTS idx_crawl_status_no_pdf
    ON crawl_jobs(status) WHERE status = 'no_pdf';
CREATE INDEX IF NOT EXISTS idx_crawl_status_needs_ocr
    ON crawl_jobs(status) WHERE status = 'needs_ocr';
