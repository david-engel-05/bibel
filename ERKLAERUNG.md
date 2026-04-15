# Wie Bibel KI funktioniert

## Das grosse Bild

Das Projekt besteht aus drei Teilen, die zusammenarbeiten:

```
Browser (Next.js)  →  Backend (FastAPI)  →  Ollama (lokale KI)
                              ↕
                        Supabase (Datenbank)
```

---

## 1. Was sind Embeddings?

Ein Embedding ist eine **Umwandlung von Text in eine Liste von Zahlen** — z.B. 768 Zahlen.

Der Trick: Texte mit ähnlicher *Bedeutung* bekommen ähnliche Zahlen. Zum Beispiel:

- „Gott liebt die Menschen" → `[0.12, -0.34, 0.87, ...]`
- „Denn also hat Gott die Welt geliebt" (Joh 3:16) → `[0.11, -0.31, 0.85, ...]` ← sehr ähnlich!
- „Das Rezept für Brot" → `[0.91, 0.22, -0.44, ...]` ← sehr verschieden

Man kann dann die **Distanz** zwischen zwei Zahlenlisten messen, um zu sehen wie ähnlich zwei Texte inhaltlich sind — ohne dass ein einziges Wort übereinstimmen muss.

---

## 2. Der Import (`import_bible.py`)

Einmalig, läuft gerade bei dir:

```
bible.json (31.172 Verse)
    ↓
Ollama nomic-embed-text
    ↓ (für jeden Vers)
768 Zahlen (Embedding)
    ↓
Supabase bible_verses Tabelle
```

Jeder Vers wird mit seinem Embedding gespeichert. Das ist die Vorbereitung für die spätere Suche.

---

## 3. Was passiert wenn du eine Frage stellst

**Schritt 1 — Frage einbetten** (`backend/main.py`, Zeile 49)
Deine Frage „Was bedeutet Nächstenliebe?" wird ebenfalls durch `nomic-embed-text` in 768 Zahlen umgewandelt.

**Schritt 2 — Ähnlichste Verse finden** (`backend/main.py`, Zeile 53)
Supabase vergleicht dein Frage-Embedding mit allen 31.172 Vers-Embeddings und gibt die 5 inhaltlich ähnlichsten zurück. Das nennt sich **semantische Suche** — im Gegensatz zur normalen Stichwort-Suche, bei der nur exakte Wörter gefunden werden.

**Schritt 3 — KI antwortet** (`backend/main.py`, Zeile 71)
Die 5 Verse werden als Kontext an `gemma4:26b` übergeben — zusammen mit deiner Frage. Das Modell formuliert dann eine Antwort auf Deutsch mit genauen Bibelstellen.

**Schritt 4 — Streaming** (`backend/main.py`, Zeile 87)
Die Antwort kommt nicht auf einmal, sondern Token für Token — wie beim Tippen. Das Backend schickt jeden Token sofort ans Frontend (SSE = Server-Sent Events), das Frontend hängt ihn an die angezeigte Nachricht an.

**Schritt 5 — Speichern** (`backend/main.py`, Zeile 93)
Frage und Antwort werden in Supabase gespeichert. Beim nächsten Öffnen der Seite lädt das Frontend den Chatverlauf automatisch aus der Datenbank.

---

## 4. Warum dieser Ansatz? (RAG)

Die KI kennt die Bibel nicht vollständig auswendig. Statt sie blind zu fragen, **suchen wir erst die passenden Verse** und geben sie als Kontext mit. Das nennt sich **RAG (Retrieval-Augmented Generation)**:

- **Retrieval** — relevante Verse aus der Datenbank finden
- **Augmented** — die KI-Anfrage mit diesen Versen anreichern
- **Generation** — die KI formuliert eine Antwort basierend auf dem Kontext

Vorteil: Die Antworten sind genauer, belegbar und halluzinieren weniger.

---

## 5. Datenbank-Struktur (Supabase)

| Tabelle | Inhalt |
|---|---|
| `bible_verses` | Alle 31.172 Verse mit Text und Embedding |
| `chat_sessions` | Jede Unterhaltung (mit UUID) |
| `chat_messages` | Alle Nachrichten einer Session (Frage + Antwort) |

---

## 6. Komponenten im Überblick

| Datei | Aufgabe |
|---|---|
| `backend/main.py` | FastAPI-Server: `/ask`, `/session`, `/history` |
| `backend/import_bible.py` | Einmaliger Import der Bibelverse mit Embeddings |
| `backend/database.py` | Supabase-Verbindung |
| `frontend/app/page.tsx` | Chat-Oberfläche im Browser |
| `supabase/schema.sql` | Datenbankstruktur (Tabellen + Suchfunktion) |
