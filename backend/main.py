from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ollama
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bibel laden
with open("bible.json", "r", encoding="utf-8") as f:
    bible = json.load(f)

class Question(BaseModel):
    question: str

@app.post("/ask")
def ask(q: Question):
    response = ollama.chat(
        model="gemma4:26b",
        messages=[
            {
                "role": "system",
                "content": """Du bist ein hilfreicher Bibel-Assistent. 
                Beantworte Fragen auf Deutsch basierend auf der Bibel.
                Gib immer die genaue Bibelstelle an (z.B. Johannes 3:16).
                Sei freundlich und verständlich."""
            },
            {
                "role": "user",
                "content": q.question
            }
        ]
    )
    return {"answer": response.message.content}