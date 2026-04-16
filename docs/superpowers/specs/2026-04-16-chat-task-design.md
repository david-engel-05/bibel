# Chat-Auftrag Feature — Design Spec

**Datum:** 2026-04-16  
**Status:** Genehmigt

## Überblick

Nutzer können einer Chat-Session einen persistenten "Auftrag" geben, den die KI über das gesamte Gespräch hinweg niemals vergisst. Der Auftrag wird in der Datenbank gespeichert, über einen Header-Button gesetzt/geändert und bei jedem `/ask`-Aufruf prominent in den System-Prompt injiziert.

---

## 1. Datenbank

**Migration:**
```sql
ALTER TABLE chat_sessions ADD COLUMN task TEXT;
```

- Nullable — Sessions ohne Auftrag verhalten sich wie bisher.
- Wird gleichzeitig mit `summary` und `summary_upto_count` gelesen.

---

## 2. Backend (`backend/main.py`)

### 2a. `_get_session()`
`task` zur SELECT-Query hinzufügen:
```python
.select("id, summary, summary_upto_count, task")
```

### 2b. `/ask`-Endpoint
Wenn `task` gesetzt (nicht leer/None), wird er ganz oben im System-Prompt eingefügt — vor dem Bibel-Assistenten-Text:

```
AUFTRAG (gilt für das gesamte Gespräch, niemals vergessen):
{task}

Du bist ein hilfreicher Bibel-Assistent.
...
```

Kein Auftrag → System-Prompt bleibt unverändert wie bisher.

### 2c. Neuer Endpoint: `PATCH /session/{session_id}/task`
Speichert oder aktualisiert den Auftrag:
```python
@app.patch("/session/{session_id}/task")
def update_task(session_id: str, body: TaskRequest, db: Client = Depends(get_supabase)):
    _get_session(session_id, db)  # 404 wenn Session nicht existiert
    db.table("chat_sessions").update({"task": body.task or None}).eq("id", session_id).execute()
    return {"ok": True}
```

Leerer String wird als `None` gespeichert (Auftrag löschen).

Neues Pydantic-Model:
```python
class TaskRequest(BaseModel):
    task: str
```

### 2d. Neuer Endpoint: `GET /session/{session_id}`
Gibt Session-Metadaten zurück (für Frontend-Restore nach Reload):
```python
@app.get("/session/{session_id}")
def get_session_info(session_id: str, db: Client = Depends(get_supabase)):
    session = _get_session(session_id, db)
    return {"task": session.get("task")}
```

---

## 3. Frontend (`frontend/app/page.tsx`)

### 3a. Neue State-Variablen
```typescript
const [task, setTask] = useState<string>("");
const [showTaskInput, setShowTaskInput] = useState(false);
const [taskInput, setTaskInput] = useState("");
```

### 3b. Session-Init
`initSession()` ruft nach dem History-Laden `GET /session/{id}` auf und setzt `task` im State.  
Gleiches gilt für `loadSession()` (beim manuellen Session-Laden).

### 3c. Header-Button
- Kleiner Button neben "NEUER CHAT" mit Stift-Icon, Tooltip "Auftrag setzen"
- Aktiv-Zustand (gold) wenn Auftrag gesetzt
- Klick öffnet Inline-Eingabefeld (gleiches Muster wie Session-Laden-Button)
- Eingabefeld ist mit aktuellem `task` vorausgefüllt
- Speichern via `PATCH /session/{id}/task` → `task` State aktualisieren
- Escape oder Klick auf Button schließt ohne Speichern
- Leereingabe → Auftrag löschen
- `newChat()` setzt `task` State auf `""` zurück (neue Session hat keinen Auftrag)

### 3d. Textarea-Scrollbar (Bonus-Fix)
`overflowY: "hidden"` → `overflowY: "auto"`, Max-Höhe bleibt 120px.  
Auto-Resize-Logik bleibt erhalten; Scrollen ist möglich wenn Inhalt die Max-Höhe übersteigt.

---

## Nicht im Scope

- Auftrag in der Chat-Anzeige sichtbar machen (kein Banner)
- Mehrere Aufträge pro Session
- Auftrags-Historie
