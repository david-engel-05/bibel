-- Migration: add ivfflat index for pgvector cosine search on bible_verses
-- Run after import_bible.py has populated bible_verses (~31k rows)
-- Execute in Supabase SQL Editor: Dashboard → SQL Editor → New query

CREATE INDEX IF NOT EXISTS bible_verses_embedding_idx
  ON bible_verses
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Refresh planner statistics so the index is used immediately
ANALYZE bible_verses;
