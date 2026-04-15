# Bibel KI v2 — Design-Dokument

**Datum:** 2026-04-15  
**Status:** Genehmigt

---

## Ziel

Bibel KI von einer einfachen Single-Page-App zu einer vollständigen Chat-Anwendung erweitern:

1. **Bessere KI-Antworten** durch RAG (Retrieval-Augmented Generation) mit pgvector in Supabase
2. **Multi-User-Support** durch anonyme Sessions (kein Login)
3. **Chat-Erlebnis** mit persistentem Verlauf und Streaming

---

## Architektur

Zwei separate Anwendungen bleiben bestehen. Neu hinzu kommen Supabase als Datenschicht und Ollama `nomic-embed-text` für Embeddings.

```
Frontend (Next.js :3000)
    → POST /ask (SSE)         → FastAPI Backend (:8000)
    → GET /history/{id}            → Ollama (nomic-embed-text → Embedding)
    → POST /session                → Supabase pgvector (Top-5 Verse)
                                   → Ollama (gemma4:26b → Stream)
                                   → Supabase (Verlauf speichern)
```

**Einmaliger Setup-Schritt:** `backend/import_bible.py` liest `bible.json`, erzeugt für jeden Vers ein Embedding via Ollama `nomic-embed-text` und schreibt alles in Supabase. Laufzeit: ~2–4h lokal. Danach nie wieder nötig.

---

## Supabase-Schema

### `bible_verses`
| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| id | bigserial PK | |
| book | text | Buchname (z.B. „Johannes") |
| chapter | int | Kapitel |
| verse | int | Versnummer |
| text | text | Vertext auf Deutsch |
| embedding | vector(768) | nomic-embed-text Output |

Index: `ivfflat` auf `embedding` für schnelle Cosine-Suche.

### `chat_sessions`
| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| id | uuid PK | Wird vom Backend generiert (POST /session), im Frontend in localStorage gespeichert |
| created_at | timestamptz | |

### `chat_messages`
| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| id | bigserial PK | |
| session_id | uuid FK | → chat_sessions.id ON DELETE CASCADE |
| role | text | `'user'` oder `'assistant'` |
| content | text | Nachrichteninhalt |
| created_at | timestamptz | |

**RAG-Abfrage:**
```sql
SELECT book, chapter, verse, text
FROM bible_verses
ORDER BY embedding <=> $question_embedding
LIMIT 5;
```

---

## Backend-Änderungen (`backend/main.py`)

### Neue Endpunkte

**`POST /session`**
- Legt eine neue anonyme Session in `chat_sessions` an
- Antwort: `{ "session_id": "<uuid>" }`

**`POST /ask`** (ersetzt bisherigen `/ask`)
- Body: `{ "question": string, "session_id": string }`
- Verarbeitung:
  1. Frage mit `ollama.embeddings(model="nomic-embed-text")` einbetten
  2. Top-5 semantisch ähnliche Verse per pgvector-Abfrage aus Supabase laden
  3. Prompt bauen: Systemanweisung + Verse als Kontext + Nutzerfrage
  4. `ollama.chat(stream=True)` auf `gemma4:26b` aufrufen
  5. Antwort-Tokens via `text/event-stream` (SSE) an Frontend streamen
  6. Vollständige Antwort nach Stream-Ende in `chat_messages` speichern
- Antwort: `text/event-stream`

**`GET /history/{session_id}`**
- Gibt alle Nachrichten der Session chronologisch zurück
- Antwort: `[ { "role": string, "content": string, "created_at": string } ]`

### Neue Datei: `backend/import_bible.py`

Einmaliges Skript:
1. `bible.json` lesen und in Einzelverse zerlegen
2. Pro Vers: `ollama.embeddings(model="nomic-embed-text")` aufrufen
3. Batch-Insert in Supabase `bible_verses` (z.B. 100 Verse pro Batch)
4. Fortschrittsbalken (tqdm) für Monitoring

---

## Frontend-Änderungen (`frontend/app/page.tsx`)

### Initialisierung
- `localStorage` prüfen: Kein `session_id`? → `POST /session` → ID speichern
- `GET /history/{session_id}` → bisherige Nachrichten in Chat-State laden

### Chat-UI
- Nachrichten als Blasen: Nutzerfragen rechts (blau), Antworten links (grau)
- Scrollbarer Verlauf im Hauptbereich
- Eingabe + Senden-Button unten fixiert
- Button oben rechts: „Neuer Chat" → neue Session anlegen, State leeren

### Streaming
- `fetch` mit `ReadableStream` auf `POST /ask`
- Nutzerfrage-Blase sofort anzeigen, dann leere Antwortblase öffnen
- Tokens live in Antwortblase einfügen (React State Update pro Chunk)
- Blinkender Cursor während Stream läuft, verschwindet nach Abschluss

---

## Abhängigkeiten

**Backend (neu):**
- `supabase` (bereits in venv installiert, aber ungenutzt)
- `tqdm` (für Import-Skript Fortschrittsanzeige)

**Frontend (neu):**
- Keine neuen Pakete — `react-markdown` und Tailwind reichen

**Ollama-Modelle (neu):**
- `nomic-embed-text` muss gepullt werden: `ollama pull nomic-embed-text`

**Supabase:**
- Neues Projekt anlegen mit aktivierter `pgvector`-Extension
- `SUPABASE_URL` und `SUPABASE_KEY` als Umgebungsvariablen im Backend

---

## Nicht in Scope

- Benutzer-Authentifizierung (Login/Registrierung)
- Mehrsprachige Bibelübersetzungen
- Suche nach Bibelstellen per Name (z.B. „Johannes 3:16" direkt nachschlagen)
- Mobile App
