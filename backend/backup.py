import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

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
