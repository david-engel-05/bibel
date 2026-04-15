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
        data=[{"id": "test-session-id"}]
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
    mock_db.rpc.return_value.execute.return_value = MagicMock(data=[])
    insert_mock = mock_db.table.return_value.insert.return_value.execute

    mock_embed = mocker.patch("main.ollama.embed")
    mock_embed.return_value = MagicMock(embeddings=[[0.1] * 768])

    def fake_chat(**kwargs):
        for token in ["Hallo "]:
            yield MagicMock(message=MagicMock(content=token))

    mocker.patch("main.ollama.chat", side_effect=fake_chat)

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
        data=[{"id": "test-session"}]
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
        data=[{"id": "test-session"}]
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
