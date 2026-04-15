# backend/import_bible.py
"""
Einmaliges Skript: bible.json → Supabase bible_verses mit Embeddings.
Laufzeit: ~2-4h für ~31.000 Verse (lokal, Ollama nomic-embed-text).
Ausführen: cd backend && source venv/bin/activate && python import_bible.py
"""
import json
import sys
from dotenv import load_dotenv
from tqdm import tqdm
import ollama
from database import get_supabase

load_dotenv()

BATCH_SIZE = 50


def load_verses(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    verses = []
    for book in data["books"]:
        for chapter in book["chapters"]:
            for v in chapter["verses"]:
                verses.append({
                    "book": book["name"],
                    "chapter": chapter["chapter"],
                    "verse": v["verse"],
                    "text": v["text"].strip(),
                })
    return verses


def embed(text: str) -> list[float]:
    result = ollama.embed(model="nomic-embed-text", input=text)
    return result.embeddings[0]


def main():
    # Sicherstellen dass nomic-embed-text vorhanden ist
    print("Prüfe nomic-embed-text Modell...")
    try:
        embed("test")
    except Exception as e:
        print(f"Fehler: {e}")
        print("Bitte zuerst ausführen: ollama pull nomic-embed-text")
        sys.exit(1)

    db = get_supabase()
    verses = load_verses("bible.json")
    print(f"{len(verses)} Verse geladen")

    for i in tqdm(range(0, len(verses), BATCH_SIZE), desc="Importiere"):
        batch = verses[i : i + BATCH_SIZE]
        rows = []
        for v in batch:
            rows.append({
                "book": v["book"],
                "chapter": v["chapter"],
                "verse": v["verse"],
                "text": v["text"],
                "embedding": embed(v["text"]),
            })
        db.table("bible_verses").insert(rows).execute()

    print("Import abgeschlossen! Jetzt den ivfflat-Index im Supabase SQL Editor anlegen (siehe Task 3 Schritt 2).")


if __name__ == "__main__":
    main()
