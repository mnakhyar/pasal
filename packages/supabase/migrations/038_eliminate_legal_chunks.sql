-- Migration 038: Eliminate legal_chunks — search directly on document_nodes
--
-- legal_chunks is a 1.7 GB denormalized copy of document_nodes content with
-- a TSVECTOR column. It doubles vacuum load and causes autovacuum stalls.
-- This migration:
--   1. Adds FTS column + indexes to document_nodes
--   2. Rewrites search_legal_chunks() to query document_nodes (same name + return shape)
--   3. Simplifies apply_revision() to remove the legal_chunks update step
--   4. Drops legal_chunks table entirely
--
-- Run via Supabase SQL editor. The ALTER TABLE may take 2-5 minutes on 533K rows.

-- ============================================================
-- Step 1: Add FTS column to document_nodes
-- ============================================================

ALTER TABLE document_nodes
ADD COLUMN IF NOT EXISTS fts TSVECTOR
GENERATED ALWAYS AS (to_tsvector('indonesian', COALESCE(content_text, ''))) STORED;

-- GIN index for TSVECTOR full-text search
CREATE INDEX IF NOT EXISTS idx_nodes_fts ON document_nodes USING GIN(fts);

-- Trigram index for ILIKE fallback (tier 3)
CREATE INDEX IF NOT EXISTS idx_nodes_trgm ON document_nodes USING GIN(content_text gin_trgm_ops);


-- ============================================================
-- Step 2: Rewrite search_legal_chunks() to query document_nodes
-- Same name, same params, same return columns — zero consumer changes.
-- ============================================================

DROP FUNCTION IF EXISTS search_legal_chunks(TEXT, INT, JSONB);

CREATE FUNCTION search_legal_chunks(
    query_text TEXT,
    match_count INT DEFAULT 10,
    metadata_filter JSONB DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    id BIGINT,
    work_id INTEGER,
    content TEXT,
    metadata JSONB,
    score FLOAT,
    snippet TEXT
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_type_filter TEXT;
BEGIN
    -- Extract type filter from metadata_filter (e.g. {"type": "UU"})
    v_type_filter := metadata_filter ->> 'type';

    -- Tier 1: websearch_to_tsquery
    RETURN QUERY
    SELECT
        dn.id::bigint,
        dn.work_id,
        dn.content_text AS content,
        jsonb_build_object(
            'type', rt.code,
            'number', w.number,
            'year', w.year::text,
            'pasal', dn.number
        ) AS metadata,
        (
            ts_rank_cd(dn.fts, websearch_to_tsquery('indonesian', query_text))
            * (1.0 + (10 - COALESCE(rt.hierarchy_level, 5)) * 0.05)
            * (1.0 + GREATEST(0, COALESCE(w.year, 2000) - 1990) * 0.005)
        )::float AS score,
        ts_headline('indonesian', dn.content_text,
            websearch_to_tsquery('indonesian', query_text),
            'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20, MaxFragments=2'
        ) AS snippet
    FROM document_nodes dn
    JOIN works w ON w.id = dn.work_id
    JOIN regulation_types rt ON rt.id = w.regulation_type_id
    WHERE dn.fts @@ websearch_to_tsquery('indonesian', query_text)
        AND dn.node_type = ANY(ARRAY['pasal','ayat','preamble','content','aturan','penjelasan_umum','penjelasan_pasal'])
        AND dn.content_text IS NOT NULL
        AND (v_type_filter IS NULL OR rt.code = v_type_filter)
    ORDER BY score DESC
    LIMIT match_count;

    IF NOT FOUND THEN
        -- Tier 2: plainto_tsquery
        RETURN QUERY
        SELECT
            dn.id::bigint,
            dn.work_id,
            dn.content_text AS content,
            jsonb_build_object(
                'type', rt.code,
                'number', w.number,
                'year', w.year::text,
                'pasal', dn.number
            ) AS metadata,
            (
                ts_rank_cd(dn.fts, plainto_tsquery('indonesian', query_text))
                * (1.0 + (10 - COALESCE(rt.hierarchy_level, 5)) * 0.05)
                * (1.0 + GREATEST(0, COALESCE(w.year, 2000) - 1990) * 0.005)
            )::float AS score,
            ts_headline('indonesian', dn.content_text,
                plainto_tsquery('indonesian', query_text),
                'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20, MaxFragments=2'
            ) AS snippet
        FROM document_nodes dn
        JOIN works w ON w.id = dn.work_id
        JOIN regulation_types rt ON rt.id = w.regulation_type_id
        WHERE dn.fts @@ plainto_tsquery('indonesian', query_text)
            AND dn.node_type = ANY(ARRAY['pasal','ayat','preamble','content','aturan','penjelasan_umum','penjelasan_pasal'])
            AND dn.content_text IS NOT NULL
            AND (v_type_filter IS NULL OR rt.code = v_type_filter)
        ORDER BY score DESC
        LIMIT match_count;
    END IF;

    IF NOT FOUND THEN
        -- Tier 3: ILIKE fallback
        RETURN QUERY
        SELECT
            dn.id::bigint,
            dn.work_id,
            dn.content_text AS content,
            jsonb_build_object(
                'type', rt.code,
                'number', w.number,
                'year', w.year::text,
                'pasal', dn.number
            ) AS metadata,
            0.01::float AS score,
            LEFT(dn.content_text, 200) AS snippet
        FROM document_nodes dn
        JOIN works w ON w.id = dn.work_id
        JOIN regulation_types rt ON rt.id = w.regulation_type_id
        WHERE (
            SELECT bool_and(dn.content_text ILIKE '%' || word || '%')
            FROM unnest(string_to_array(trim(query_text), ' ')) AS word
            WHERE length(word) > 2
        )
            AND dn.node_type = ANY(ARRAY['pasal','ayat','preamble','content','aturan','penjelasan_umum','penjelasan_pasal'])
            AND dn.content_text IS NOT NULL
            AND (v_type_filter IS NULL OR rt.code = v_type_filter)
        ORDER BY dn.id
        LIMIT match_count;
    END IF;
END;
$$;


-- ============================================================
-- Step 3: Simplify apply_revision() — remove legal_chunks update
-- The GENERATED ALWAYS fts column on document_nodes auto-updates
-- when content_text changes, so no manual TSVECTOR maintenance needed.
-- ============================================================

CREATE OR REPLACE FUNCTION apply_revision(
    p_node_id INTEGER,
    p_work_id INTEGER,
    p_new_content TEXT,
    p_revision_type VARCHAR(30),
    p_reason TEXT,
    p_suggestion_id BIGINT DEFAULT NULL,
    p_actor_type VARCHAR(20) DEFAULT 'system',
    p_created_by UUID DEFAULT NULL
) RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_old_content TEXT;
    v_node_type VARCHAR(20);
    v_node_number VARCHAR(50);
    v_node_path LTREE;
    v_revision_id BIGINT;
BEGIN
    -- 1. Fetch current content from document_nodes
    SELECT content_text, node_type, number, path
    INTO v_old_content, v_node_type, v_node_number, v_node_path
    FROM document_nodes
    WHERE id = p_node_id AND work_id = p_work_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Node % not found in work %', p_node_id, p_work_id;
    END IF;

    -- 2. INSERT into revisions (old + new content)
    INSERT INTO revisions (
        work_id, node_id, node_type, node_number, node_path,
        old_content, new_content, revision_type, reason,
        suggestion_id, actor_type, created_by
    ) VALUES (
        p_work_id, p_node_id, v_node_type, v_node_number, v_node_path,
        v_old_content, p_new_content, p_revision_type, p_reason,
        p_suggestion_id, p_actor_type, p_created_by
    ) RETURNING id INTO v_revision_id;

    -- 3. UPDATE document_nodes.content_text + revision_id
    --    (fts TSVECTOR column auto-updates via GENERATED ALWAYS)
    UPDATE document_nodes
    SET content_text = p_new_content,
        revision_id = v_revision_id
    WHERE id = p_node_id;

    -- 4. If suggestion_id: UPDATE suggestions.status='approved'
    IF p_suggestion_id IS NOT NULL THEN
        UPDATE suggestions
        SET status = 'approved',
            revision_id = v_revision_id,
            reviewed_by = p_created_by,
            reviewed_at = NOW()
        WHERE id = p_suggestion_id;
    END IF;

    RETURN v_revision_id;
END;
$$;


-- ============================================================
-- Step 4: Drop legal_chunks table
-- Frees ~1.7 GB immediately.
-- ============================================================

DROP TABLE IF EXISTS legal_chunks CASCADE;
