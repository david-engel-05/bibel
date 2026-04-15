# Context Summarization — Design Spec

**Date:** 2026-04-15
**Status:** Approved

## Goal

Prevent unbounded context growth in long chat sessions. As conversations grow, the full history is currently sent to Ollama on every request, causing increasing latency and CPU/GPU load. This feature caps what Ollama sees while preserving semantic continuity via a rolling summary.

## Scope

Backend only (`backend/main.py` + one Supabase migration). No frontend changes.

---

## Architecture

### Core Principle

Raw messages are **never deleted** from Supabase. Only what is sent to Ollama is changed. The summary is a compressed representation of older messages, stored in `chat_sessions.summary`.

### Context Assembly (per `/ask` request)

**When session has ≤ 10 messages (no summary yet):**
```
[system prompt + RAG context]
[all messages]
[new question]
```

**When session has > 10 messages (summary exists):**
```
[system prompt + RAG context]
[summary message, role: "system"]
[last 6 messages]
[new question]
```

The summary message is injected as a second system message with a clear prefix so Ollama knows it is prior-context:

```
Zusammenfassung des bisherigen Gesprächs:
<summary text>
```

### Summarization Trigger

After every `/ask` response (inside the existing `BackgroundTask` that saves the assistant message), check if total message count will exceed 10. If yes, call Ollama to summarize all messages except the last 6, and upsert the result into `chat_sessions.summary`.

This means:
- At 11 messages: summarize messages 1–5, keep 6–11 fresh
- At 13 messages: summarize messages 1–7, keep 8–13 fresh
- The summary always covers `messages[0 .. count-7]`

Since this runs in the background after the stream completes, there is zero added latency for the user.

### Summarization Prompt

Ollama is called with `ollama.chat` (non-streaming, same `CHAT_MODEL`) using this system prompt:

```
Du fasst ein Bibelgespräch zusammen. Erstelle eine strukturierte, deutschsprachige Zusammenfassung, die folgendes festhält:
- Diskutierte Bibelstellen und -themen (mit genauen Versen, z.B. Johannes 3:16)
- Wichtige Schlüsse und Erkenntnisse aus dem Gespräch
- Offene Fragen oder Themen, auf die man zurückkommen wollte
Halte die Zusammenfassung kompakt (maximal 300 Wörter).
```

The messages to summarize are passed as the conversation content.

---

## Data Model

### New column

```sql
ALTER TABLE chat_sessions
  ADD COLUMN IF NOT EXISTS summary TEXT;
```

Default is `NULL` (no summary until threshold is reached).

### No other schema changes

`chat_messages` is unchanged. Raw messages remain fully intact.

---

## Files Changed

| File | Change |
|------|--------|
| `supabase/migrations/20260415100000_add_session_summary.sql` | Add `summary TEXT` column to `chat_sessions` |
| `backend/main.py` | Update `/ask`: context assembly uses summary + recent window; BackgroundTask runs summarization when threshold exceeded |

---

## Constants (configurable via env vars)

| Constant | Default | Meaning |
|----------|---------|---------|
| `SUMMARY_THRESHOLD` | `10` | Min messages before summarization kicks in |
| `SUMMARY_FRESH_WINDOW` | `6` | Number of recent messages always sent raw |

---

## Error Handling

- If the summarization Ollama call fails (network error, timeout), the exception is caught and logged but **does not fail the request** — the BackgroundTask exits silently. The next request will retry summarization.
- If `summary` is `None` (not yet generated), the full history is sent as before.
- If history fetch fails inside BackgroundTask, exception is caught and logged.

---

## What Is Preserved

The summary prompt explicitly captures:
- Specific Bible verse references (e.g. Johannes 3:16, Römer 5:8)
- Discussion themes and conclusions
- Open questions or unresolved topics

This ensures "zurück zu dem Vers von vorhin" or "nochmal zum Ursprungsthema" still works even after many turns.

---

## What Is NOT Preserved

- Exact wording of old messages (paraphrased in summary)
- Precise quote retrieval from early messages

This is acceptable for a conversational Bible Q&A app where semantic continuity matters more than verbatim recall.

---

## Testing

- Unit test: context assembly uses summary + recent window when `summary` is set
- Unit test: context assembly uses full history when no summary and count ≤ threshold
- Unit test: summarization is triggered when message count after save exceeds threshold
- Unit test: summarization failure does not raise (silent catch)
- Existing tests for `/ask` and `/history` must continue to pass
