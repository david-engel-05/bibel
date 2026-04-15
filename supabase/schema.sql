-- supabase/schema.sql
-- Im Supabase SQL Editor ausführen (Dashboard → SQL Editor → New query)

-- pgvector aktivieren
create extension if not exists vector;

-- Bibelverse mit Embeddings
create table if not exists bible_verses (
  id        bigserial primary key,
  book      text    not null,
  chapter   int     not null,
  verse     int     not null,
  text      text    not null,
  embedding vector(768)
);

-- Anonyme Sessions
create table if not exists chat_sessions (
  id         uuid primary key default gen_random_uuid(),
  created_at timestamptz default now()
);

-- Gesprächsnachrichten
create table if not exists chat_messages (
  id         bigserial primary key,
  session_id uuid not null references chat_sessions(id) on delete cascade,
  role       text not null check (role in ('user', 'assistant')),
  content    text not null,
  created_at timestamptz default now()
);

-- RPC-Funktion für Vektorsuche (wird nach dem Import mit Index ergänzt)
create or replace function match_verses(
  query_embedding vector(768),
  match_count     int default 5
)
returns table (
  id      bigint,
  book    text,
  chapter int,
  verse   int,
  text    text
)
language sql stable
as $$
  select id, book, chapter, verse, text
  from bible_verses
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- Performance: ivfflat index for cosine similarity search
-- Run this separately after bible_verses is populated (import_bible.py)
-- CREATE INDEX IF NOT EXISTS bible_verses_embedding_idx
--   ON bible_verses USING ivfflat (embedding vector_cosine_ops)
--   WITH (lists = 100);
-- ANALYZE bible_verses;
