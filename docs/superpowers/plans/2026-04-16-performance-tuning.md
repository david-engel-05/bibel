# Performance Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Mac fan activity by separating the summary model (`gemma3:4b`), adding a cooldown delay between answer and summary, capping Ollama context/output via `num_ctx`/`num_predict`, and adding an automated every-2-hours backup of chat data from Supabase Cloud to local JSON files.

**Architecture:** Performance changes are in `backend/main.py`. Backup is a standalone `backend/backup.py` script using the existing Supabase client, writing timestamped JSON to `backups/`, triggered by a Mac crontab entry.

**Tech Stack:** Python, FastAPI, Ollama Python SDK (`ollama.chat` accepts `model`, `messages`, `stream`, `options`), pytest + pytest-mock, Supabase Python client, Mac `crontab`.

---

## File Map

| File | Change |
|------|--------|
| `backend/main.py` | Add 4 constants, `import time` at top, `options` to both chat calls, `SUMMARY_MODEL` in `_maybe_summarize`, `time.sleep` in `save_and_maybe_summarize` |
| `backend/tests/test_endpoints.py` | Set `SUMMARY_DELAY=0` env default, add 3 new tests: options in chat, SUMMARY_MODEL in summary, sleep before summary |
| `backend/backup.py` | Standalone backup script: export `chat_sessions` + `chat_messages` to `backups/YYYY-MM-DD_HH-MM-SS.json`, prune old files |
| `backend/tests/test_backup.py` | Unit tests for backup script |

---

### Task 1: Add new constants and `import time`

**Files:**
- Modify: `backend/main.py:1-19`
- Test: `backend/tests/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Add at the bottom of `backend/tests/test_endpoints.py`:

```python
def test_new_constants_have_correct_defaults():
    import main
    assert main.SUMMARY_MODEL == "gemma3:4b"
    assert main.CHAT_NUM_CTX == 3072
    assert main.CHAT_NUM_PREDICT == 600
    assert main.SUMMARY_DELAY == 0  # 0 because test file sets SUMMARY_DELAY=0
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd backend && source venv/bin/activate
pytest tests/test_endpoints.py::test_new_constants_have_correct_defaults -v
```

Expected: `AttributeError: module 'main' has no attribute 'SUMMARY_MODEL'`

- [ ] **Step 3: Set `SUMMARY_DELAY=0` at the top of the test file**

The test file already has `os.environ.setdefault(...)` calls inside functions. Add these two lines at the very top of `backend/tests/test_endpoints.py`, before any imports:

```python
import os
os.environ.setdefault("SUMMARY_DELAY", "0")
```

This ensures `SUMMARY_DELAY` is `0` before `main` is imported, so background tasks don't slow down tests.

- [ ] **Step 4: Add `import time` and the four constants to `backend/main.py`**

Add `import time` on the line after `import os` (line 1):

```python
import os
import time
```

Then add these four lines after the existing `SUMMARY_BATCH_SIZE` constant (after line 19):

```python
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gemma3:4b")
CHAT_NUM_CTX = int(os.environ.get("CHAT_NUM_CTX", "3072"))
CHAT_NUM_PREDICT = int(os.environ.get("CHAT_NUM_PREDICT", "600"))
SUMMARY_DELAY = int(os.environ.get("SUMMARY_DELAY", "5"))
```

Also remove the `import sys` line from inside `_maybe_summarize` (around line 95) and add `import sys` to the top-level imports:

```python
import os
import sys
import time
```

- [ ] **Step 5: Run the test to confirm it passes**

```bash
pytest tests/test_endpoints.py::test_new_constants_have_correct_defaults -v
```

Expected: `PASSED`

- [ ] **Step 6: Run all tests to confirm nothing is broken**

```bash
pytest tests/ -v
```

Expected: all existing tests `PASSED`

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/tests/test_endpoints.py
git commit -m "feat: add SUMMARY_MODEL, CHAT_NUM_CTX, CHAT_NUM_PREDICT, SUMMARY_DELAY constants"
```

---

### Task 2: Pass `options` to the main streaming chat call

**Files:**
- Modify: `backend/main.py` — the `ollama.chat(stream=True, ...)` call inside `generate()`
- Test: `backend/tests/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Add at the bottom of `backend/tests/test_endpoints.py`:

```python
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
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
pytest tests/test_endpoints.py::test_ask_passes_num_ctx_and_num_predict_to_ollama_chat -v
```

Expected: `AssertionError: assert 'options' in {...}`

- [ ] **Step 3: Add `options` to the streaming `ollama.chat` call in `generate()`**

In `backend/main.py`, find the `ollama.chat` call inside `generate()` (the one with `stream=True`). It currently looks like:

```python
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
```

Add `options={"num_ctx": CHAT_NUM_CTX, "num_predict": CHAT_NUM_PREDICT},` after `stream=True,`:

```python
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
    options={"num_ctx": CHAT_NUM_CTX, "num_predict": CHAT_NUM_PREDICT},
):
```

- [ ] **Step 4: Run the new test to confirm it passes**

```bash
pytest tests/test_endpoints.py::test_ask_passes_num_ctx_and_num_predict_to_ollama_chat -v
```

Expected: `PASSED`

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_endpoints.py
git commit -m "feat: pass num_ctx and num_predict options to main ollama chat call"
```

---

### Task 3: Use `SUMMARY_MODEL` and `options` in `_maybe_summarize`

**Files:**
- Modify: `backend/main.py` — the `ollama.chat(stream=False, ...)` call inside `_maybe_summarize`
- Test: `backend/tests/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Add at the bottom of `backend/tests/test_endpoints.py`:

```python
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
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
pytest tests/test_endpoints.py::test_maybe_summarize_uses_summary_model_not_chat_model -v
```

Expected: `AssertionError` because currently `CHAT_MODEL` is used.

- [ ] **Step 3: Update `_maybe_summarize` to use `SUMMARY_MODEL` and `options`**

In `backend/main.py`, find the `ollama.chat` call inside `_maybe_summarize`. It currently looks like:

```python
summary_response = ollama.chat(
    model=CHAT_MODEL,
    messages=[
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        *[{"role": m["role"], "content": m["content"]} for m in to_summarize],
    ],
    stream=False,
)
```

Change it to:

```python
summary_response = ollama.chat(
    model=SUMMARY_MODEL,
    messages=[
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        *[{"role": m["role"], "content": m["content"]} for m in to_summarize],
    ],
    stream=False,
    options={"num_ctx": CHAT_NUM_CTX, "num_predict": CHAT_NUM_PREDICT},
)
```

Also remove the now-redundant `import sys` from inside `_maybe_summarize` if it's still there (it was moved to top level in Task 1).

- [ ] **Step 4: Run the new test to confirm it passes**

```bash
pytest tests/test_endpoints.py::test_maybe_summarize_uses_summary_model_not_chat_model -v
```

Expected: `PASSED`

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_endpoints.py
git commit -m "feat: use SUMMARY_MODEL and options in _maybe_summarize"
```

---

### Task 4: Add cooldown delay before summarization

**Files:**
- Modify: `backend/main.py` — `save_and_maybe_summarize` closure inside `ask()`
- Test: `backend/tests/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Add at the bottom of `backend/tests/test_endpoints.py`:

```python
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
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
pytest tests/test_endpoints.py::test_ask_background_sleeps_before_summarize -v
```

Expected: `AssertionError: Expected call: sleep(0)` — `time.sleep` not yet called.

- [ ] **Step 3: Add `time.sleep(SUMMARY_DELAY)` to `save_and_maybe_summarize`**

In `backend/main.py`, find the `save_and_maybe_summarize` closure inside `ask()`. It currently looks like:

```python
def save_and_maybe_summarize():
    db.table("chat_messages").insert(
        {
            "session_id": req.session_id,
            "role": "assistant",
            "content": "".join(full_response),
        }
    ).execute()
    _maybe_summarize(req.session_id, db, SUMMARY_THRESHOLD, SUMMARY_FRESH_WINDOW, SUMMARY_BATCH_SIZE, summary_upto_count)
```

Add `time.sleep(SUMMARY_DELAY)` between the two statements:

```python
def save_and_maybe_summarize():
    db.table("chat_messages").insert(
        {
            "session_id": req.session_id,
            "role": "assistant",
            "content": "".join(full_response),
        }
    ).execute()
    time.sleep(SUMMARY_DELAY)
    _maybe_summarize(req.session_id, db, SUMMARY_THRESHOLD, SUMMARY_FRESH_WINDOW, SUMMARY_BATCH_SIZE, summary_upto_count)
```

- [ ] **Step 4: Run the new test to confirm it passes**

```bash
pytest tests/test_endpoints.py::test_ask_background_sleeps_before_summarize -v
```

Expected: `PASSED`

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_endpoints.py
git commit -m "feat: add SUMMARY_DELAY cooldown before background summarization"
```

---

### Task 5: Patch `time.sleep` in existing background-task tests

Existing tests that exercise `/ask` run the BackgroundTask synchronously. Without patching `time.sleep`, they'd call the real sleep (0 seconds due to `SUMMARY_DELAY=0` env default, so they still pass). This task adds the mock explicitly for clarity and resilience.

**Files:**
- Modify: `backend/tests/test_endpoints.py`

- [ ] **Step 1: Add `mocker.patch("main.time.sleep")` to existing `/ask` tests**

In `backend/tests/test_endpoints.py`, add `mocker.patch("main.time.sleep")` to these three existing tests — place it after the `mocker.patch("main.ollama.chat", ...)` line in each:

- `test_ask_streams_response`
- `test_ask_saves_assistant_message_via_background`
- `test_ask_includes_history_in_ollama_call`
- `test_ask_uses_full_history_when_no_summary`
- `test_ask_uses_summary_and_recent_window_when_summary_exists`

Example for `test_ask_streams_response`:

```python
# after: mocker.patch("main.ollama.chat", side_effect=fake_chat)
mocker.patch("main.time.sleep")
```

- [ ] **Step 2: Run all tests**

```bash
cd backend && source venv/bin/activate
pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_endpoints.py
git commit -m "test: mock time.sleep in existing /ask tests"
```

---

### Task 6: Document `.env` changes

**Files:**
- Modify: `backend/.env` (if it exists) — add the three new optional variables

- [ ] **Step 1: Check if `.env` exists**

```bash
ls backend/.env 2>/dev/null && echo "exists" || echo "missing"
```

- [ ] **Step 2a: If `.env` exists — append the new variables**

Add to `backend/.env`:

```env
# Performance tuning — Ollama
SUMMARY_MODEL=gemma3:4b
CHAT_NUM_CTX=3072
CHAT_NUM_PREDICT=600
# SUMMARY_DELAY=5  (default: 5 seconds cooldown between answer and summary)
```

- [ ] **Step 2b: If `.env` does not exist — create it**

```bash
cat > backend/.env << 'EOF'
# Performance tuning — Ollama
SUMMARY_MODEL=gemma3:4b
CHAT_NUM_CTX=3072
CHAT_NUM_PREDICT=600
# SUMMARY_DELAY=5  (default: 5 seconds cooldown between answer and summary)
EOF
```

- [ ] **Step 3: Pull the summary model if not yet available**

```bash
ollama pull gemma3:4b
```

Expected: model downloaded or already present message.

- [ ] **Step 4: Commit**

`.env` is typically gitignored. Only commit if it isn't:

```bash
git status backend/.env
# If tracked:
git add backend/.env
git commit -m "chore: document new performance tuning env vars in .env"
```

---

---

### Task 7: Create `backend/backup.py`

Standalone script that exports `chat_sessions` and `chat_messages` to a timestamped JSON file in `backups/`. Keeps only the last 48 files (= 4 days at 2h intervals).

**Files:**
- Create: `backend/backup.py`
- Create: `backend/tests/test_backup.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backup.py`:

```python
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

    # After run: 48 old + 1 new = 49, then pruned to keep=48
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
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd backend && source venv/bin/activate
pytest tests/test_backup.py -v
```

Expected: `ModuleNotFoundError: No module named 'backup'`

- [ ] **Step 3: Implement `backend/backup.py`**

Create `backend/backup.py`:

```python
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Import get_supabase from the sibling module
sys.path.insert(0, str(Path(__file__).parent))
from database import get_supabase

DEFAULT_BACKUP_DIR = Path(__file__).parent.parent / "backups"
DEFAULT_KEEP = 48  # 4 days at 2-hour intervals


def run_backup(backup_dir: Path = DEFAULT_BACKUP_DIR, keep: int = DEFAULT_KEEP) -> Path:
    """Export chat_sessions and chat_messages to a timestamped JSON file.

    Returns the path of the written backup file.
    Prunes oldest files so at most `keep` backups remain after writing.
    """
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    db = get_supabase()

    sessions = db.table("chat_sessions").select("*").execute().data
    messages = db.table("chat_messages").select("*").execute().data

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = backup_dir / f"{timestamp}.json"
    backup_file.write_text(
        json.dumps({"chat_sessions": sessions, "chat_messages": messages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Prune oldest files
    all_files = sorted(backup_dir.glob("*.json"))
    for old_file in all_files[:-keep]:
        old_file.unlink()

    return backup_file


if __name__ == "__main__":
    written = run_backup()
    print(f"Backup gespeichert: {written}")
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
pytest tests/test_backup.py -v
```

Expected: all 3 tests `PASSED`

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Add `backups/` to `.gitignore`**

Open `.gitignore` (or create it in the project root if missing) and add:

```
backups/
```

- [ ] **Step 7: Commit**

```bash
git add backend/backup.py backend/tests/test_backup.py .gitignore
git commit -m "feat: add backup.py to export chat data from Supabase every 2h"
```

---

### Task 8: Set up Mac crontab for automatic backups

**Files:** None (crontab is user-level, not tracked in git)

- [ ] **Step 1: Find the absolute paths needed**

```bash
which python  # while venv is active — e.g. /Users/yanisdangeli/Documents/bibel/backend/venv/bin/python
pwd           # run from project root — e.g. /Users/yanisdangeli/Documents/bibel
```

Note both paths for the next step.

- [ ] **Step 2: Open the crontab editor**

```bash
crontab -e
```

This opens in `vi`. Press `i` to insert, add the line below, then press `Esc`, type `:wq`, press Enter.

```cron
0 */2 * * * cd /Users/yanisdangeli/Documents/bibel/backend && /Users/yanisdangeli/Documents/bibel/backend/venv/bin/python backup.py >> /Users/yanisdangeli/Documents/bibel/backups/backup.log 2>&1
```

Replace the paths with the actual ones from Step 1.

This runs `backup.py` every 2 hours on the hour (00:00, 02:00, 04:00, …).

- [ ] **Step 3: Verify crontab was saved**

```bash
crontab -l
```

Expected: the line above appears in the output.

- [ ] **Step 4: Test the backup manually**

```bash
cd backend && source venv/bin/activate && python backup.py
```

Expected output: `Backup gespeichert: /Users/yanisdangeli/Documents/bibel/backups/2026-04-16_HH-MM-SS.json`

Check that the file exists and contains data:

```bash
ls -lh ../backups/
```

---

## Verification

After all tasks are complete, run the full test suite:

```bash
cd backend && source venv/bin/activate
pytest tests/ -v
```

Expected: all tests green.

Then start the backend and send a question via the frontend. Verify:
1. Answer streams normally
2. The Mac fan is quieter during summarization (noticeable after ~10 messages in a session)
3. `backups/` directory is created and populated by cron every 2 hours
