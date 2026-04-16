import os
import sys
import time
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from supabase import Client
import ollama
from dotenv import load_dotenv
from database import get_supabase

load_dotenv()

EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gemma4:26b")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")]
SUMMARY_THRESHOLD = int(os.environ.get("SUMMARY_THRESHOLD", "10"))
SUMMARY_FRESH_WINDOW = int(os.environ.get("SUMMARY_FRESH_WINDOW", "6"))
SUMMARY_BATCH_SIZE = int(os.environ.get("SUMMARY_BATCH_SIZE", "4"))
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gemma3:4b")
CHAT_NUM_CTX = int(os.environ.get("CHAT_NUM_CTX", "3072"))
CHAT_NUM_PREDICT = int(os.environ.get("CHAT_NUM_PREDICT", "600"))
SUMMARY_DELAY = int(os.environ.get("SUMMARY_DELAY", "5"))
SUMMARY_SYSTEM_PROMPT = (
    "Du fasst ein Bibelgespräch zusammen. Erstelle eine strukturierte, "
    "deutschsprachige Zusammenfassung, die folgendes festhält:\n"
    "- Diskutierte Bibelstellen und -themen (mit genauen Versen, z.B. Johannes 3:16)\n"
    "- Wichtige Schlüsse und Erkenntnisse aus dem Gespräch\n"
    "- Offene Fragen oder Themen, auf die man zurückkommen wollte\n"
    "- Wenn der nutzer eine aufgebe gegeben hat, fasse diese bitte auch in der Zusammenfassung mit auf. stelle es an den anfang der Zusammenfassung\n"
    "Halte die Zusammenfassung kompakt (maximal 400 Wörter)."
)


class AskRequest(BaseModel):
    question: str
    session_id: str


class TaskRequest(BaseModel):
    task: str


app = FastAPI()


def _get_session(session_id: str, db: Client) -> dict:
    """Returns session row (id, summary, summary_upto_count, task) or raises 404."""
    result = (
        db.table("chat_sessions")
        .select("id, summary, summary_upto_count, task")
        .eq("id", session_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return result.data[0]


def _assemble_history(
    all_history: list[dict],
    summary: str | None,
    summary_upto_count: int,
) -> list[dict]:
    """
    Returns the message list to pass to Ollama.
    If summary is set, prepends it as a system message and appends all messages
    after the summarized portion (all_history[summary_upto_count:]) — no gap.
    Otherwise returns the full history unchanged.
    """
    if summary:
        return [
            {
                "role": "system",
                "content": f"Zusammenfassung des bisherigen Gesprächs:\n{summary}",
            },
            *all_history[summary_upto_count:],
        ]
    return all_history


def _maybe_summarize(
    session_id: str,
    db: Client,
    threshold: int,
    fresh_window: int,
    batch_size: int,
    current_upto_count: int,
) -> None:
    """
    Called inside BackgroundTask. Only runs a new summarization when at least
    `batch_size` messages have accumulated beyond the last summary boundary.
    This prevents re-summarizing on every single request.

    Logic:
      msgs_to_cover = total_messages - fresh_window
      Only summarize if msgs_to_cover >= current_upto_count + batch_size

    Re-reads summary_upto_count from DB before the guard so that concurrent
    requests cannot both trigger a redundant summarization.

    All exceptions are swallowed — summary is best-effort, but logged to stderr.
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
        msgs_to_cover = len(msgs) - fresh_window
        # Re-read the current boundary from DB to handle concurrent requests
        session_result = (
            db.table("chat_sessions")
            .select("summary_upto_count")
            .eq("id", session_id)
            .execute()
        )
        if session_result.data:
            current_upto_count = session_result.data[0].get("summary_upto_count") or 0
        if msgs_to_cover < current_upto_count + batch_size:
            return  # not enough new messages to justify a re-summarization
        to_summarize = msgs[:msgs_to_cover]
        summary_response = ollama.chat(
            model=SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                *[{"role": m["role"], "content": m["content"]} for m in to_summarize],
                {"role": "user", "content": "Bitte erstelle jetzt die Zusammenfassung des obigen Gesprächs."},
            ],
            stream=False,
            options={"num_ctx": CHAT_NUM_CTX, "num_predict": CHAT_NUM_PREDICT},
        )
        summary_text = summary_response.message.content
        db.table("chat_sessions").update(
            {"summary": summary_text, "summary_upto_count": msgs_to_cover}
        ).eq("id", session_id).execute()
    except Exception as exc:
        print(f"[summarize] session={session_id} error={exc}", file=sys.stderr)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/session")
def create_session(db: Client = Depends(get_supabase)):
    result = db.table("chat_sessions").insert({}).execute()
    return {"session_id": result.data[0]["id"]}


@app.get("/session/{session_id}")
def get_session_info(session_id: str, db: Client = Depends(get_supabase)):
    session = _get_session(session_id, db)
    return {"task": session.get("task")}


@app.patch("/session/{session_id}/task")
def update_task(session_id: str, body: TaskRequest, db: Client = Depends(get_supabase)):
    _get_session(session_id, db)
    db.table("chat_sessions").update(
        {"task": body.task or None}
    ).eq("id", session_id).execute()
    return {"ok": True}


@app.get("/history/{session_id}")
def get_history(session_id: str, db: Client = Depends(get_supabase)):
    _get_session(session_id, db)
    result = (
        db.table("chat_messages")
        .select("role, content, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    return result.data


@app.post("/ask")
def ask(req: AskRequest, db: Client = Depends(get_supabase)):
    session = _get_session(req.session_id, db)
    current_summary = session.get("summary")
    summary_upto_count = session.get("summary_upto_count") or 0

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
    history_for_ollama = _assemble_history(all_history, current_summary, summary_upto_count)

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
            think=False,
            options={"num_ctx": CHAT_NUM_CTX, "num_predict": CHAT_NUM_PREDICT},
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
        time.sleep(SUMMARY_DELAY)
        _maybe_summarize(req.session_id, db, SUMMARY_THRESHOLD, SUMMARY_FRESH_WINDOW, SUMMARY_BATCH_SIZE, summary_upto_count)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        background=BackgroundTask(save_and_maybe_summarize),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
