# backend/tests/test_endpoints.py
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient


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
