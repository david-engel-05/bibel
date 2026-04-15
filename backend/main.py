from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import Client
import ollama
from dotenv import load_dotenv
from database import get_supabase

load_dotenv()

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
