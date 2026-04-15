"use client";
import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";

type Message = {
  role: "user" | "assistant";
  content: string;
};

const API = "http://localhost:8000";

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    initSession();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function initSession() {
    let id = localStorage.getItem("session_id");
    if (!id) {
      const res = await fetch(`${API}/session`, { method: "POST" });
      const data = await res.json();
      id = data.session_id as string;
      localStorage.setItem("session_id", id);
    }
    setSessionId(id);
    const histRes = await fetch(`${API}/history/${id}`);
    const history: { role: "user" | "assistant"; content: string }[] =
      await histRes.json();
    setMessages(history.map((m) => ({ role: m.role, content: m.content })));
  }

  async function newChat() {
    const res = await fetch(`${API}/session`, { method: "POST" });
    const data = await res.json();
    const id = data.session_id as string;
    localStorage.setItem("session_id", id);
    setSessionId(id);
    setMessages([]);
  }

  async function send() {
    if (!input.trim() || streaming || !sessionId) return;
    const question = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    setStreaming(true);

    const res = await fetch(`${API}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: sessionId }),
    });

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();

    outer: while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const token = line.slice(6);
        if (token === "[DONE]") break outer;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          return [
            ...prev.slice(0, -1),
            { ...last, content: last.content + token },
          ];
        });
      }
    }
    setStreaming(false);
  }

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
        <h1 className="text-xl font-bold">Bibel KI</h1>
        <button
          onClick={newChat}
          className="text-sm text-gray-400 hover:text-white px-3 py-1 rounded border border-gray-700 hover:border-gray-500 transition-colors"
        >
          Neuer Chat
        </button>
      </header>

      {/* Nachrichten */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.length === 0 && (
          <p className="text-center text-gray-500 mt-24 text-sm">
            Stelle eine Frage zur Bibel
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-2xl px-4 py-3 rounded-2xl ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-100"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>
                    {msg.content ||
                      (streaming && i === messages.length - 1 ? "▋" : "")}
                  </ReactMarkdown>
                </div>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Eingabe */}
      <div className="border-t border-gray-800 px-4 py-4 shrink-0">
        <div className="flex gap-2 max-w-3xl mx-auto">
          <input
            className="flex-1 bg-gray-800 rounded-xl px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            placeholder="z.B. Was bedeutet Johannes 3:16?"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            disabled={streaming}
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed px-5 py-3 rounded-xl font-medium transition-colors"
          >
            {streaming ? "..." : "Senden"}
          </button>
        </div>
      </div>
    </div>
  );
}
