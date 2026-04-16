import os
os.environ.setdefault("SUMMARY_DELAY", "0")
# backend/tests/test_endpoints.py
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient


def test_get_supabase_returns_singleton():
    """get_supabase() must return the same client object on repeated calls."""
    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    # Reset the singleton between test runs
    import database
    database._client = None

    from database import get_supabase
    client_a = get_supabase()
    client_b = get_supabase()
    assert client_a is client_b


def make_mock_db():
    """Hilfsfunktion: gibt einen vorkonfigurierten Supabase-Mock zurück."""
    db = MagicMock()
    return db


# --- /session ---

def test_create_session_returns_uuid():
    mock_db = make_mock_db()
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "123e4567-e89b-12d3-a456-426614174000"}]
    )

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    response = client.post("/session")

    assert response.status_code == 200
    assert response.json() == {"session_id": "123e4567-e89b-12d3-a456-426614174000"}
    mock_db.table.assert_called_once_with("chat_sessions")
    app.dependency_overrides.clear()


# --- /history ---

def test_get_history_returns_messages():
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[
            {"role": "user", "content": "Hallo", "created_at": "2026-04-15T10:00:00Z"},
            {"role": "assistant", "content": "Antwort", "created_at": "2026-04-15T10:00:01Z"},
        ]
    )

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    session_id = "123e4567-e89b-12d3-a456-426614174000"
    response = client.get(f"/history/{session_id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["role"] == "user"
    assert data[1]["role"] == "assistant"
    app.dependency_overrides.clear()


def test_get_history_empty_for_new_session():
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "neue-session-id"}]
    )
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[]
    )

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    response = client.get("/history/neue-session-id")

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


# --- /ask ---

def test_ask_streams_response(mocker):
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session-id", "summary": None, "summary_upto_count": 0}]
    )

    # Verse-Suche gibt 2 Verse zurück
    mock_db.rpc.return_value.execute.return_value = MagicMock(
        data=[
            {"book": "Johannes", "chapter": 3, "verse": 16, "text": "Denn also hat Gott..."},
            {"book": "Römer", "chapter": 8, "verse": 28, "text": "Wir wissen aber..."},
        ]
    )
    # chat_messages.insert gibt keine relevante Antwort
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    # Ollama-Embedding mocken
    mock_embed = mocker.patch("main.ollama.embed")
    mock_embed.return_value = MagicMock(embeddings=[[0.1] * 768])

    # Ollama-Chat-Stream mocken: liefert 3 Chunks
    def fake_chat(**kwargs):
        for token in ["Gott ", "liebt ", "dich."]:
            yield MagicMock(message=MagicMock(content=token))

    mocker.patch("main.ollama.chat", side_effect=fake_chat)
    mocker.patch("main.time.sleep")

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    response = client.post(
        "/ask",
        json={"question": "Was bedeutet Liebe?", "session_id": "test-session-id"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "data: Gott " in body
    assert "data: liebt " in body
    assert "data: dich." in body
    assert "data: [DONE]" in body
    app.dependency_overrides.clear()


def test_ask_saves_assistant_message_via_background(mocker):
    """Assistant message must be saved even if we rely on background task."""
    mock_db = make_mock_db()
    # Session exists, no summary yet
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "123e4567-e89b-12d3-a456-426614174000", "summary": None}]
    )
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    insert_mock = mock_db.table.return_value.insert.return_value.execute

    mock_embed = mocker.patch("main.ollama.embed")
    mock_embed.return_value = MagicMock(embeddings=[[0.1] * 768])

    def fake_chat(**kwargs):
        for token in ["Hallo "]:
            yield MagicMock(message=MagicMock(content=token))

    mocker.patch("main.ollama.chat", side_effect=fake_chat)
    mocker.patch("main.time.sleep")

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    response = client.post(
        "/ask",
        json={"question": "Test?", "session_id": "123e4567-e89b-12d3-a456-426614174000"},
    )

    assert response.status_code == 200
    # insert must have been called twice: once for user, once for assistant
    assert insert_mock.call_count == 2
    app.dependency_overrides.clear()


def test_get_history_returns_404_for_unknown_session():
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[]
    )

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    response = client.get("/history/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_ask_returns_404_for_unknown_session(mocker):
    mock_db = make_mock_db()
    # session lookup returns empty
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[]
    )

    mock_embed = mocker.patch("main.ollama.embed")
    mock_embed.return_value = MagicMock(embeddings=[[0.1] * 768])

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    response = client.post(
        "/ask",
        json={"question": "Test?", "session_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_ask_returns_503_when_ollama_unavailable(mocker):
    """If ollama.embed raises, /ask must return 503."""
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": None}]
    )

    mocker.patch("main.ollama.embed", side_effect=Exception("Connection refused"))

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    response = client.post(
        "/ask",
        json={"question": "Test?", "session_id": "test-session"},
    )

    assert response.status_code == 503
    assert "Ollama" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_ask_includes_history_in_ollama_call(mocker):
    """Previous messages from DB must be passed to ollama.chat."""
    mock_db = make_mock_db()

    # Session exists
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": None}]
    )
    # History: one prior exchange
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[
            {"role": "user", "content": "Was ist Glaube?"},
            {"role": "assistant", "content": "Glaube ist Vertrauen in Gott."},
        ]
    )
    # Verse search
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    # Insert mock
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    mock_embed = mocker.patch("main.ollama.embed")
    mock_embed.return_value = MagicMock(embeddings=[[0.1] * 768])

    chat_mock = mocker.patch("main.ollama.chat", return_value=iter([
        MagicMock(message=MagicMock(content="Ja."))
    ]))
    mocker.patch("main.time.sleep")

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    client.post(
        "/ask",
        json={"question": "Erkläre das genauer", "session_id": "test-session"},
    )

    # ollama.chat must have been called with history messages
    call_kwargs = chat_mock.call_args[1]
    messages = call_kwargs["messages"]
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    # The prior user message must appear before the current one
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    assert "Was ist Glaube?" in user_msgs
    assert "Erkläre das genauer" in user_msgs
    app.dependency_overrides.clear()


# --- _assemble_history ---

def test_assemble_history_no_summary_returns_full_history():
    from main import _assemble_history
    history = [
        {"role": "user", "content": "Frage 1"},
        {"role": "assistant", "content": "Antwort 1"},
        {"role": "user", "content": "Frage 2"},
        {"role": "assistant", "content": "Antwort 2"},
    ]
    result = _assemble_history(history, summary=None, summary_upto_count=0)
    assert result == history


def test_assemble_history_with_summary_injects_system_message():
    from main import _assemble_history
    history = [{"role": "user", "content": f"Nachricht {i}"} for i in range(10)]
    result = _assemble_history(history, summary="Test Zusammenfassung", summary_upto_count=4)
    assert result[0]["role"] == "system"
    assert "Test Zusammenfassung" in result[0]["content"]


def test_assemble_history_with_summary_uses_upto_count_slice():
    from main import _assemble_history
    history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    # summary covers msgs 0-3; fresh = history[4:] = 6 msgs, no gap
    result = _assemble_history(history, summary="Zusammenfassung", summary_upto_count=4)
    assert len(result) == 7  # 1 summary system msg + 6 fresh
    assert result[1:] == history[4:]


def test_assemble_history_empty_history_with_summary():
    from main import _assemble_history
    result = _assemble_history([], summary="Zusammenfassung", summary_upto_count=0)
    assert len(result) == 1
    assert result[0]["role"] == "system"
    assert "Zusammenfassung" in result[0]["content"]


# --- _maybe_summarize ---

def test_maybe_summarize_not_triggered_at_or_below_threshold(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[{"role": "user", "content": "msg"}] * 10
    )
    mock_chat = mocker.patch("main.ollama.chat")
    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6, batch_size=4, current_upto_count=0)
    mock_chat.assert_not_called()


def _setup_summarize_mocks(mock_db, msgs, current_upto_count):
    """Wires both DB query mocks needed by _maybe_summarize:
    - chat_messages (with .order) → msgs
    - chat_sessions fresh read (without .order) → current_upto_count
    """
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=msgs
    )
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"summary_upto_count": current_upto_count}]
    )


def test_maybe_summarize_not_triggered_below_batch_size(mocker):
    """With 11 msgs and upto_count=5, msgs_to_cover=5 < 5+4=9 → skip."""
    from main import _maybe_summarize
    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    _setup_summarize_mocks(mock_db, msgs, current_upto_count=5)
    mock_chat = mocker.patch("main.ollama.chat")
    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6, batch_size=4, current_upto_count=5)
    mock_chat.assert_not_called()


def test_maybe_summarize_triggered_above_threshold(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    _setup_summarize_mocks(mock_db, msgs, current_upto_count=0)
    mock_chat = mocker.patch("main.ollama.chat")
    mock_chat.return_value = MagicMock(message=MagicMock(content="Zusammenfassung Text"))

    # upto_count=0, batch_size=4 → msgs_to_cover=5 >= 0+4 → trigger
    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6, batch_size=4, current_upto_count=0)

    mock_chat.assert_called_once()
    call_kwargs = mock_chat.call_args[1]
    assert call_kwargs["messages"][0]["role"] == "system"
    # msgs[:5] = 5 messages to summarize
    summarized = call_kwargs["messages"][1:]
    assert len(summarized) == 5
    assert call_kwargs.get("stream") is False


def test_maybe_summarize_saves_correct_summary_text(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    _setup_summarize_mocks(mock_db, msgs, current_upto_count=0)
    mock_chat = mocker.patch("main.ollama.chat")
    mock_chat.return_value = MagicMock(message=MagicMock(content="Meine Zusammenfassung"))

    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6, batch_size=4, current_upto_count=0)

    update_call = mock_db.table.return_value.update.call_args
    # Must save both summary text and upto_count (11-6=5)
    assert update_call[0][0] == {"summary": "Meine Zusammenfassung", "summary_upto_count": 5}


def test_maybe_summarize_silently_ignores_ollama_failure(mocker):
    from main import _maybe_summarize
    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    _setup_summarize_mocks(mock_db, msgs, current_upto_count=0)
    mocker.patch("main.ollama.chat", side_effect=Exception("Ollama unavailable"))

    # Must not raise
    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6, batch_size=4, current_upto_count=0)


# --- /ask integration: context assembly ---

def test_ask_uses_full_history_when_no_summary(mocker):
    """When session has no summary, all history messages are passed to ollama.chat."""
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": None, "summary_upto_count": 0}]
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
    mocker.patch("main.time.sleep")

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
    """When session has a summary, ollama.chat receives the summary system msg + last 6 messages."""
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": "Bisherige Zusammenfassung über Johannes 3:16", "summary_upto_count": 4}]
    )
    # 10 history messages — only last 6 should reach Ollama raw
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
    mocker.patch("main.time.sleep")

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    client.post("/ask", json={"question": "Frage", "session_id": "test-session"})

    call_kwargs = chat_mock.call_args[1]
    messages = call_kwargs["messages"]

    # messages[0]: FastAPI system prompt (RAG context)
    assert messages[0]["role"] == "system"
    # messages[1]: summary injected by _assemble_history
    assert messages[1]["role"] == "system"
    assert "Bisherige Zusammenfassung" in messages[1]["content"]
    # Only 6 raw history messages (not all 10), plus the new question at the end
    # So total: 1 (system) + 1 (summary) + 6 (raw history) + 1 (new question) = 9
    assert len(messages) == 9
    app.dependency_overrides.clear()


def test_new_constants_have_correct_defaults():
    import main
    assert main.SUMMARY_MODEL == "gemma3:4b"
    assert main.CHAT_NUM_CTX == 3072
    assert main.CHAT_NUM_PREDICT == 600
    assert main.SUMMARY_DELAY == 0  # 0 because test file sets SUMMARY_DELAY=0


def test_ask_passes_num_ctx_and_num_predict_to_ollama_chat(mocker):
    """ollama.chat for the main answer must receive num_ctx and num_predict options."""
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": None, "summary_upto_count": 0}]
    )
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[]
    )
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    mocker.patch("main.ollama.embed", return_value=MagicMock(embeddings=[[0.1] * 768]))
    chat_mock = mocker.patch("main.ollama.chat", return_value=iter([
        MagicMock(message=MagicMock(content="Antwort."))
    ]))
    mocker.patch("main.time.sleep")

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase, CHAT_NUM_CTX, CHAT_NUM_PREDICT
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    client.post("/ask", json={"question": "Test?", "session_id": "test-session"})

    # The streaming call is the first call to ollama.chat
    first_call_kwargs = chat_mock.call_args_list[0][1]
    assert "options" in first_call_kwargs
    assert first_call_kwargs["options"]["num_ctx"] == CHAT_NUM_CTX
    assert first_call_kwargs["options"]["num_predict"] == CHAT_NUM_PREDICT
    app.dependency_overrides.clear()


def test_maybe_summarize_uses_summary_model_not_chat_model(mocker):
    """_maybe_summarize must call ollama.chat with SUMMARY_MODEL, not CHAT_MODEL."""
    from main import _maybe_summarize, SUMMARY_MODEL, CHAT_MODEL

    assert SUMMARY_MODEL != CHAT_MODEL, "Test only meaningful when models differ"

    mock_db = MagicMock()
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(11)]
    _setup_summarize_mocks(mock_db, msgs, current_upto_count=0)

    mock_chat = mocker.patch("main.ollama.chat")
    mock_chat.return_value = MagicMock(message=MagicMock(content="Zusammenfassung"))

    _maybe_summarize("session-1", mock_db, threshold=10, fresh_window=6, batch_size=4, current_upto_count=0)

    mock_chat.assert_called_once()
    call_kwargs = mock_chat.call_args[1]
    assert call_kwargs["model"] == SUMMARY_MODEL
    assert call_kwargs["model"] != CHAT_MODEL


def test_ask_background_sleeps_before_summarize(mocker):
    """save_and_maybe_summarize must call time.sleep(SUMMARY_DELAY) before _maybe_summarize."""
    mock_db = make_mock_db()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "test-session", "summary": None, "summary_upto_count": 0}]
    )
    mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[]
    )
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

    mocker.patch("main.ollama.embed", return_value=MagicMock(embeddings=[[0.1] * 768]))
    mocker.patch("main.ollama.chat", return_value=iter([
        MagicMock(message=MagicMock(content="Antwort."))
    ]))
    sleep_mock = mocker.patch("main.time.sleep")

    import os
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")

    from main import app, get_supabase, SUMMARY_DELAY
    app.dependency_overrides[get_supabase] = lambda: mock_db
    client = TestClient(app)

    client.post("/ask", json={"question": "Test?", "session_id": "test-session"})

    sleep_mock.assert_called_once_with(SUMMARY_DELAY)
    app.dependency_overrides.clear()
