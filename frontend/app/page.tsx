"use client";
import { useState } from "react";
import ReactMarkdown from "react-markdown";

export default function Home() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);

  const ask = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setAnswer("");
    const res = await fetch("http://localhost:8000/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    setAnswer(data.answer);
    setLoading(false);
  };

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center p-8">
      <h1 className="text-3xl font-bold mb-2">Bibel KI</h1>
      <p className="text-gray-400 mb-8">Stelle eine Frage zur Bibel</p>

      <div className="w-full max-w-2xl flex gap-2">
        <input
          className="flex-1 bg-gray-800 rounded-lg px-4 py-3 outline-none"
          placeholder="z.B. Was bedeutet Johannes 3:16?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
        />
        <button
          onClick={ask}
          className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg font-medium"
        >
          Fragen
        </button>
      </div>

      {loading && <p className="mt-8 text-gray-400">Antwort wird geladen...</p>}

      {answer && (
        <div className="mt-8 w-full max-w-2xl bg-gray-800 rounded-lg p-6">
          <ReactMarkdown>{answer}</ReactMarkdown>
        </div>
      )}
    </main>
  );
}