from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import Client
import ollama
from dotenv import load_dotenv
from database import get_supabase

load_dotenv()


class AskRequest(BaseModel):
    question: str
    session_id: str


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/session")
def create_session(db: Client = Depends(get_supabase)):
    result = db.table("chat_sessions").insert({}).execute()
    return {"session_id": result.data[0]["id"]}


@app.get("/history/{session_id}")
def get_history(session_id: str, db: Client = Depends(get_supabase)):
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
    # 1. Frage einbetten
    embed_result = ollama.embed(model="nomic-embed-text", input=req.question)
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

    # 4. Stream generieren und Antwort anschließend persistieren
    full_response: list[str] = []

    def generate():
        for chunk in ollama.chat(
            model="gemma4:26b",
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
                {"role": "user", "content": req.question},
            ],
            stream=True,
        ):
            token = chunk.message.content
            if token:
                full_response.append(token)
                yield f"data: {token}\n\n"

        db.table("chat_messages").insert(
            {
                "session_id": req.session_id,
                "role": "assistant",
                "content": "".join(full_response),
            }
        ).execute()
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
