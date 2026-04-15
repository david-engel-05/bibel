# Context Summarization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap the Ollama context window for long chats by storing a rolling German-language summary of older messages in Supabase, so response latency stays constant regardless of conversation length.

**Architecture:** Three new pure helper functions (`_get_session`, `_assemble_history`, `_maybe_summarize`) are extracted into `backend/main.py`. The `/ask` endpoint uses `_assemble_history` to build the Ollama message list (summary system message + last 6 raw messages instead of full history). After streaming, the existing `BackgroundTask` is extended to call `_maybe_summarize`, which re-summarizes whenever total message count exceeds 10. Summary text is stored in a new `summary TEXT` column on `chat_sessions`. Raw messages are never deleted.

**Tech Stack:** FastAPI, Python, Ollama (`ollama` SDK), Supabase Python client, pytest + pytest-mock

---

## File Map

| File | Action |
|------|--------|
| `supabase/migrations/20260415100000_add_session_summary.sql` | Create — adds `summary TEXT` column |
| `backend/main.py` | Modify — add constants, replace `_require_session` with `_get_session`, add `_assemble_history`, `_maybe_summarize`, update `/ask` |
| `backend/tests/test_endpoints.py` | Modify — add 7 new tests, update 1 existing test |

---

## Task 1: Database migration

**Files:**
- Create: `supabase/migrations/20260415100000_add_session_summary.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- supabase/migrations/20260415100000_add_session_summary.sql
ALTER TABLE chat_sessions
  ADD COLUMN IF NOT EXISTS summary TEXT;
```

- [ ] **Step 2: Commit**

```bash
cd /Users/yanisdangeli/Documents/bibel && git add supabase/migrations/20260415100000_add_session_summary.sql && git commit -m "feat: add summary column to chat_sessions"
```

---

## Task 2: Add `_assemble_history` helper + tests

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_endpoints.py`

`_assemble_history` is a pure function — no DB, no Ollama. Test it by importing directly.

- [ ] **Step 1: Write the failing tests**

Add these four tests at the end of `backend/tests/test_endpoints.py`:

```python
# --- _assemble_history ---

def test_assemble_history_no_summary_returns_full_history():
    from main import _assemble_history
    history = [
        {"role": "user", "content": "Frage 1"},
        {"role": "assistant", "content": "Antwort 1"},
        {"role": "user", "content": "Frage 2"},
        {"role": "assistant", "content": "Antwort 2"},
    ]
    result = _assemble_history(history, summary=None, fresh_window=6)
    assert result == history


def test_assemble_history_with_summary_injects_system_message():
    from main import _assemble_history
    history = [{"role": "user", "content": f"Nachricht {i}"} for i in range(10)]
    result = _assemble_history(history, summary="Test Zusammenfassung", fresh_window=6)
    assert result[0]["role"] == "system"
    assert "Test Zusammenfassung" in result[0]["content"]


def test_assemble_history_with_summary_keeps_only_fresh_window():
    from main import _assemble_history
    history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    result = _assemble_history(history, summary="Zusammenfassung", fresh_window=6)
    # 1 summary system message + 6 fresh messages
    assert len(result) == 7
    assert result[1:] == history[-6:]


def test_assemble_history_empty_history_with_summary():
    from main import _assemble_history
    result = _assemble_history([], summary="Zusammenfassung", fresh_window=6)
    assert len(result) == 1
    assert result[0]["role"] == "system"
    assert "Zusammenfassung" in result[0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/test_endpoints.py::test_assemble_history_no_summary_returns_full_history tests/test_endpoints.py::test_assemble_history_with_summary_injects_system_message tests/test_endpoints.py::test_assemble_history_with_summary_keeps_only_fresh_window tests/test_endpoints.py::test_assemble_history_empty_history_with_summary -v 2>&1 | tail -15
```

Expected: 4 errors with `ImportError: cannot import name '_assemble_history'`

- [ ] **Step 3: Add `_assemble_history` to `main.py`**

Add this function directly after the `_require_session` function (around line 37), before `app.add_middleware`:

```python
def _assemble_history(
    all_history: list[dict],
    summary: str | None,
    fresh_window: int,
) -> list[dict]:
    """
    Returns the message list to pass to Ollama.
    If summary is set, prepends it as a system message and returns only
    the last `fresh_window` raw messages.  Otherwise returns full history.
    """
    if summary:
        return [
            {
                "role": "system",
                "content": f"Zusammenfassung des bisherigen Gesprächs:\n{summary}",
            },
            *all_history[-fresh_window:],
        ]
    return all_history
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/test_endpoints.py::test_assemble_history_no_summary_returns_full_history tests/test_endpoints.py::test_assemble_history_with_summary_injects_system_message tests/test_endpoints.py::test_assemble_history_with_summary_keeps_only_fresh_window tests/test_endpoints.py::test_assemble_history_empty_history_with_summary -v 2>&1 | tail -10
```

Expected: 4 PASSED

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/ -v 2>&1 | tail -20
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
cd /Users/yanisdangeli/Documents/bibel && git add backend/main.py backend/tests/test_endpoints.py && git commit -m "feat: add _assemble_history helper with tests"
```

---

## Task 3: Replace `_require_session` with `_get_session`

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_endpoints.py`

`_get_session` fetches `id, summary` instead of just `id`, and returns the row so callers can read the summary without a second DB call. This replaces `_require_session` everywhere.

- [ ] **Step 1: Add constants to `main.py`**

At the top of `main.py`, after the existing env var lines (around line 16), add:

```python
SUMMARY_THRESHOLD = int(os.environ.get("SUMMARY_THRESHOLD", "10"))
SUMMARY_FRESH_WINDOW = int(os.environ.get("SUMMARY_FRESH_WINDOW", "6"))
SUMMARY_SYSTEM_PROMPT = (
    "Du fasst ein Bibelgespräch zusammen. Erstelle eine strukturierte, "
    "deutschsprachige Zusammenfassung, die folgendes festhält:\n"
    "- Diskutierte Bibelstellen und -themen (mit genauen Versen, z.B. Johannes 3:16)\n"
    "- Wichtige Schlüsse und Erkenntnisse aus dem Gespräch\n"
    "- Offene Fragen oder Themen, auf die man zurückkommen wollte\n"
    "Halte die Zusammenfassung kompakt (maximal 300 Wörter)."
)
```

- [ ] **Step 2: Replace `_require_session` with `_get_session` in `main.py`**

Find:
```python
def _require_session(session_id: str, db: Client) -> None:
    """Raises 404 if session_id does not exist in chat_sessions."""
    result = (
        db.table("chat_sessions")
        .select("id")
        .eq("id", session_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
```

Replace with:
```python
def _get_session(session_id: str, db: Client) -> dict:
    """Returns session row (id, summary) or raises 404."""
    result = (
        db.table("chat_sessions")
        .select("id, summary")
        .eq("id", session_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return result.data[0]
```

- [ ] **Step 3: Update call sites in `main.py`**

In `get_history`, find:
```python
    _require_session(session_id, db)
```
Replace with:
```python
    _get_session(session_id, db)
```

In `ask`, find:
```python
    _require_session(req.session_id, db)
```
Replace with:
```python
    _get_session(req.session_id, db)
```

(Note: Task 5 will use the return value. For now, just calling it is enough to keep existing tests green.)

- [ ] **Step 4: Update `test_ask_saves_assistant_message_via_background` in `test_endpoints.py`**

This test has no explicit session mock, so `_get_session`'s `result.data[0].get("summary")` would return a truthy MagicMock. Fix it by adding an explicit session mock.

Find the beginning of `test_ask_saves_assistant_message_via_background`:
```python
def test_ask_saves_assistant_message_via_background(mocker):
    """Assistant message must be saved even if we rely on background task."""
    mock_db = make_mock_db()
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    insert_mock = mock_db.table.return_value.insert.return_value.execute
```

Replace with:
```python
def test_ask_saves_assistant_message_via_background(mocker):
    """Assistant message must be saved even if we rely on background task."""
    mock_db = make_mock_db()
    # Session exists, no summary yet
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "123e4567-e89b-12d3-a456-426614174000", "summary": None}]
    )
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    insert_mock = mock_db.table.return_value.insert.return_value.execute
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
cd /Users/yanisdangeli/Documents/bibel && git add backend/main.py backend/tests/test_endpoints.py && git commit -m "refactor: replace _require_session with _get_session returning session row"
```

---

## Task 4: Add `_maybe_summarize` helper + tests

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Add these four tests at the end of `backend/tests/test_endpoints.py`:

```python
# --- _maybe_summarize ---

def test_maybe_summarize_not_triggered_at_or_below_threshold(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[{"role": "user", "content": "msg"}] * 10
    )
    mock_chat = mocker.patch("main.ollama.chat")
    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6)
    mock_chat.assert_not_called()


def test_maybe_summarize_triggered_above_threshold(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=msgs
    )
    mock_chat = mocker.patch("main.ollama.chat")
    mock_chat.return_value = MagicMock(message=MagicMock(content="Zusammenfassung Text"))

    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6)

    mock_chat.assert_called_once()
    call_kwargs = mock_chat.call_args[1]
    # First message must be the summary system prompt
    assert call_kwargs["messages"][0]["role"] == "system"
    # 11 total - 6 fresh = 5 messages to summarize
    summarized = call_kwargs["messages"][1:]
    assert len(summarized) == 5
    # stream must be False (not a generator call)
    assert call_kwargs.get("stream") is False


def test_maybe_summarize_saves_correct_summary_text(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=msgs
    )
    mock_chat = mocker.patch("main.ollama.chat")
    mock_chat.return_value = MagicMock(message=MagicMock(content="Meine Zusammenfassung"))

    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6)

    update_call = mock_db.table.return_value.update.call_args
    assert update_call[0][0] == {"summary": "Meine Zusammenfassung"}


def test_maybe_summarize_silently_ignores_ollama_failure(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=msgs
    )
    mocker.patch("main.ollama.chat", side_effect=Exception("Ollama unavailable"))

    # Must not raise
    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/test_endpoints.py::test_maybe_summarize_not_triggered_at_or_below_threshold tests/test_endpoints.py::test_maybe_summarize_triggered_above_threshold tests/test_endpoints.py::test_maybe_summarize_saves_correct_summary_text tests/test_endpoints.py::test_maybe_summarize_silently_ignores_ollama_failure -v 2>&1 | tail -15
```

Expected: 4 errors with `ImportError: cannot import name '_maybe_summarize'`

- [ ] **Step 3: Add `_maybe_summarize` to `main.py`**

Add this function directly after `_assemble_history` (before `app.add_middleware`):

```python
def _maybe_summarize(
    session_id: str,
    db: Client,
    threshold: int,
    fresh_window: int,
) -> None:
    """
    Called inside BackgroundTask. Fetches all messages for the session.
    If count > threshold, summarizes all-except-last-fresh_window using Ollama
    and upserts the result into chat_sessions.summary.
    All exceptions are silently swallowed — summary is best-effort.
    """
    try:
        msgs_result = (
            db.table("chat_messages")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        msgs = msgs_result.data
        if len(msgs) <= threshold:
            return
        to_summarize = msgs[:-fresh_window]
        summary_response = ollama.chat(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                *[{"role": m["role"], "content": m["content"]} for m in to_summarize],
            ],
            stream=False,
        )
        summary_text = summary_response.message.content
        db.table("chat_sessions").update({"summary": summary_text}).eq(
            "id", session_id
        ).execute()
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/test_endpoints.py::test_maybe_summarize_not_triggered_at_or_below_threshold tests/test_endpoints.py::test_maybe_summarize_triggered_above_threshold tests/test_endpoints.py::test_maybe_summarize_saves_correct_summary_text tests/test_endpoints.py::test_maybe_summarize_silently_ignores_ollama_failure -v 2>&1 | tail -10
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
cd /Users/yanisdangeli/Documents/bibel && git add backend/main.py backend/tests/test_endpoints.py && git commit -m "feat: add _maybe_summarize helper with tests"
```

---

## Task 5: Wire everything into `/ask` + integration tests

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_endpoints.py`

- [ ] **Step 1: Write two new integration tests**

Add these two tests at the end of `backend/tests/test_endpoints.py`:

```python
# --- /ask integration: context assembly ---

def test_ask_uses_full_history_when_no_summary(mocker):
    """When session has no summary, all history is passed to ollama.chat."""
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": None}]
    )
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[
            {"role": "user", "content": "Alte Frage"},
            {"role": "assistant", "content": "Alte Antwort"},
        ]
    )
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    mocker.patch("main.ollama.embed", return_value=MagicMock(embeddings=[[0.1] * 768]))
    chat_mock = mocker.patch("main.ollama.chat", return_value=iter([
        MagicMock(message=MagicMock(content="Antwort."))
    ]))

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    client.post("/ask", json={"question": "Neue Frage", "session_id": "test-session"})

    call_kwargs = chat_mock.call_args[1]
    messages = call_kwargs["messages"]
    contents = [m["content"] for m in messages]
    assert "Alte Frage" in contents
    assert "Alte Antwort" in contents
    app.dependency_overrides.clear()


def test_ask_uses_summary_and_recent_window_when_summary_exists(mocker):
    """When session has a summary, ollama.chat receives summary system msg + last 6 messages."""
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": "Bisherige Zusammenfassung über Johannes 3:16"}]
    )
    # History has 10 messages — only last 6 should reach Ollama
    history_msgs = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(10)
    ]
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=history_msgs
    )
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    mocker.patch("main.ollama.embed", return_value=MagicMock(embeddings=[[0.1] * 768]))
    chat_mock = mocker.patch("main.ollama.chat", return_value=iter([
        MagicMock(message=MagicMock(content="Antwort."))
    ]))

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    client.post("/ask", json={"question": "Frage", "session_id": "test-session"})

    call_kwargs = chat_mock.call_args[1]
    messages = call_kwargs["messages"]

    # First message: FastAPI system prompt
    assert messages[0]["role"] == "system"
    # Second message: summary injected by _assemble_history
    assert messages[1]["role"] == "system"
    assert "Bisherige Zusammenfassung" in messages[1]["content"]
    # Only 6 raw history messages (not all 10)
    raw_history_in_call = [m for m in messages if m not in [messages[0], messages[1], messages[-1]]]
    assert len(raw_history_in_call) == 6
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/test_endpoints.py::test_ask_uses_full_history_when_no_summary tests/test_endpoints.py::test_ask_uses_summary_and_recent_window_when_summary_exists -v 2>&1 | tail -15
```

Expected: 2 FAILED (tests run but assertions fail because `/ask` still uses the old `_require_session` path)

- [ ] **Step 3: Update `/ask` in `main.py`**

Replace the entire `/ask` function with:

```python
@app.post("/ask")
def ask(req: AskRequest, db: Client = Depends(get_supabase)):
    session = _get_session(req.session_id, db)
    current_summary = session.get("summary")

    # 0. Gesprächsverlauf laden
    history_result = (
        db.table("chat_messages")
        .select("role, content")
        .eq("session_id", req.session_id)
        .order("created_at")
        .execute()
    )
    all_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history_result.data
    ]
    history_for_ollama = _assemble_history(all_history, current_summary, SUMMARY_FRESH_WINDOW)

    # 1. Frage einbetten
    try:
        embed_result = ollama.embed(model=EMBED_MODEL, input=req.question)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama nicht erreichbar: {e}",
        )
    question_embedding = embed_result.embeddings[0]

    # 2. Top-5 semantisch ähnliche Verse aus Supabase laden
    verses_result = db.rpc(
        "match_verses",
        {"query_embedding": question_embedding, "match_count": 5},
    ).execute()
    context = "\n".join(
        f"{v['book']} {v['chapter']}:{v['verse']} — {v['text']}"
        for v in verses_result.data
    )

    # 3. Nutzernachricht speichern
    db.table("chat_messages").insert(
        {"session_id": req.session_id, "role": "user", "content": req.question}
    ).execute()

    # 4. Stream generieren; Antwort + optionale Zusammenfassung via BackgroundTask
    full_response: list[str] = []

    def generate():
        for chunk in ollama.chat(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Du bist ein hilfreicher Bibel-Assistent.\n"
                        "Beantworte Fragen auf Deutsch basierend auf der Bibel.\n"
                        "Gib immer die genaue Bibelstelle an (z.B. Johannes 3:16).\n"
                        "Sei freundlich und verständlich.\n\n"
                        f"Relevante Bibelstellen:\n{context}"
                    ),
                },
                *history_for_ollama,
                {"role": "user", "content": req.question},
            ],
            stream=True,
        ):
            token = chunk.message.content
            if token:
                full_response.append(token)
                yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    def save_and_maybe_summarize():
        db.table("chat_messages").insert(
            {
                "session_id": req.session_id,
                "role": "assistant",
                "content": "".join(full_response),
            }
        ).execute()
        _maybe_summarize(req.session_id, db, SUMMARY_THRESHOLD, SUMMARY_FRESH_WINDOW)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        background=BackgroundTask(save_and_maybe_summarize),
    )
```

- [ ] **Step 4: Run the two new tests to verify they pass**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/test_endpoints.py::test_ask_uses_full_history_when_no_summary tests/test_endpoints.py::test_ask_uses_summary_and_recent_window_when_summary_exists -v 2>&1 | tail -10
```

Expected: 2 PASSED

- [ ] **Step 5: Run the full test suite**

```bash
cd /Users/yanisdangeli/Documents/bibel/backend && source venv/bin/activate && pytest tests/ -v 2>&1 | tail -25
```

Expected: all tests pass (10 original + 8 new = 18 total)

- [ ] **Step 6: Commit**

```bash
cd /Users/yanisdangeli/Documents/bibel && git add backend/main.py backend/tests/test_endpoints.py && git commit -m "feat: cap Ollama context with rolling summary in BackgroundTask"
```

---

## Self-Review

**Spec coverage:**
- ✅ `summary TEXT` column on `chat_sessions` — Task 1
- ✅ Context assembly: summary system message + last 6 raw messages — `_assemble_history` in Task 2, wired in Task 5
- ✅ Full history when no summary — `_assemble_history(history, None, ...)` returns unchanged history
- ✅ Summarization triggered when count > 10 — `_maybe_summarize` threshold check
- ✅ Summarizes all-except-last-6 — `msgs[:-fresh_window]`
- ✅ Runs in BackgroundTask (no added latency) — `save_and_maybe_summarize` in Task 5
- ✅ German summary prompt preserving Bible refs, themes, open questions — `SUMMARY_SYSTEM_PROMPT` constant
- ✅ Failure is silent — `except Exception: pass` in `_maybe_summarize`
- ✅ Raw messages never deleted — only `summary` column is written
- ✅ `SUMMARY_THRESHOLD` and `SUMMARY_FRESH_WINDOW` configurable via env vars — Task 3

**Placeholder scan:** No TBDs. All steps have code.

**Type consistency:**
- `_assemble_history(all_history, current_summary, SUMMARY_FRESH_WINDOW)` — defined in Task 2, called in Task 5 ✅
- `_maybe_summarize(req.session_id, db, SUMMARY_THRESHOLD, SUMMARY_FRESH_WINDOW)` — defined in Task 4, called in Task 5 ✅
- `_get_session(req.session_id, db)` → returns `dict` → `.get("summary")` — defined in Task 3, used in Task 5 ✅
- `SUMMARY_THRESHOLD`, `SUMMARY_FRESH_WINDOW`, `SUMMARY_SYSTEM_PROMPT` — defined in Task 3, used in Tasks 4 and 5 ✅
