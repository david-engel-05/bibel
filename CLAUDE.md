# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Bibel KI** is a German-language Bible Q&A web app. Users ask questions about the Bible and receive AI-generated answers with scripture references, powered by a local Ollama LLM.

## Architecture

Three components:

```
backend/   FastAPI (Python) — localhost:8000
frontend/  Next.js (TypeScript) — localhost:3000
Supabase   pgvector (bible_verses) + chat_sessions + chat_messages
```

**Request flow:** `page.tsx` → `POST /ask` (SSE) → FastAPI → Ollama `nomic-embed-text` (Embedding) → Supabase pgvector (Top-5 Verse) → Ollama `gemma4:26b` (Stream) → SSE-Tokens an Browser.

**One-time setup:** `backend/import_bible.py` fills `bible_verses` with embeddings (~31,000 verses, ~2-4h).

## Commands

### Backend

```bash
cd backend
source venv/bin/activate
python main.py          # starts uvicorn on :8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev             # dev server on :3000
npm run build           # production build
npm run lint            # ESLint
```

## Next.js Version Warning

The frontend uses **Next.js 16** which has breaking API changes from earlier versions. Before modifying frontend code, read the relevant guide in `frontend/node_modules/next/dist/docs/` — conventions and file structure may differ from older Next.js knowledge.

## Key Files

| File | Purpose |
|------|---------|
| `backend/main.py` | Entire backend: FastAPI app, CORS, `/ask` endpoint, Ollama call, system prompt |
| `frontend/app/page.tsx` | Entire UI: question input, fetch call, markdown answer display |
| `frontend/app/layout.tsx` | Root layout with metadata and font |
| `backend/database.py` | Supabase client factory (`get_supabase()`) |
| `backend/import_bible.py` | One-time bible import script (Embeddings → Supabase) |
| `backend/tests/test_endpoints.py` | pytest tests for all 3 endpoints |
| `supabase/schema.sql` | DDL for all tables + `match_verses` RPC function |

## System Prompt (German)

The AI is instructed to answer in German, always cite exact Bible references (e.g. `Johannes 3:16`), and be friendly. This lives in `backend/main.py` in the `ollama.chat` call.
