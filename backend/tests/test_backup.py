# backend/tests/test_backup.py
import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")


def make_mock_db(sessions, messages):
    db = MagicMock()
    db.table.return_value.select.return_value.execute.side_effect = [
        MagicMock(data=sessions),
        MagicMock(data=messages),
    ]
    return db


def test_backup_creates_json_file(tmp_path):
    from backup import run_backup

    sessions = [{"id": "abc", "summary": None, "created_at": "2026-04-16T10:00:00Z"}]
    messages = [{"session_id": "abc", "role": "user", "content": "Hallo", "created_at": "2026-04-16T10:00:01Z"}]
    mock_db = make_mock_db(sessions, messages)

    with patch("backup.get_supabase", return_value=mock_db):
        run_backup(backup_dir=tmp_path)

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["chat_sessions"] == sessions
    assert data["chat_messages"] == messages


def test_backup_prunes_old_files(tmp_path):
    from backup import run_backup

    # Create 50 dummy backup files
    for i in range(50):
        (tmp_path / f"2026-04-15_0{i:02d}-00-00.json").write_text("{}")

    mock_db = make_mock_db([], [])
    with patch("backup.get_supabase", return_value=mock_db):
        run_backup(backup_dir=tmp_path, keep=48)

    # After run: 50 old + 1 new = 51, then pruned to keep=48
    assert len(list(tmp_path.glob("*.json"))) == 48


def test_backup_filename_contains_timestamp(tmp_path):
    from backup import run_backup

    mock_db = make_mock_db([], [])
    with patch("backup.get_supabase", return_value=mock_db):
        run_backup(backup_dir=tmp_path)

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    # Filename format: YYYY-MM-DD_HH-MM-SS.json
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json", files[0].name)
