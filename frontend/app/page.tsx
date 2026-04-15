"use client";
import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";

type Message = {
  role: "user" | "assistant";
  content: string;
};

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function CrossIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="17" y="4" width="6" height="32" rx="1.5" fill="currentColor" />
      <rect x="6" y="13" width="28" height="6" rx="1.5" fill="currentColor" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}
function CopyIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function LoadSessionIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [showSessionInput, setShowSessionInput] = useState(false);
  const [sessionInput, setSessionInput] = useState("");
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [copySuccess, setCopySuccess] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sessionInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { initSession(); }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Warn before reload/close while streaming
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (streaming) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [streaming]);

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
    const history: { role: "user" | "assistant"; content: string }[] = await histRes.json();
    setMessages(history.map((m) => ({ role: m.role, content: m.content })));
  }

  async function newChat() {
    const res = await fetch(`${API}/session`, { method: "POST" });
    const data = await res.json();
    const id = data.session_id as string;
    localStorage.setItem("session_id", id);
    setSessionId(id);
    setMessages([]);
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  async function copySessionId() {
    if (!sessionId) return;
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 1500);
    } catch {
      // clipboard access denied — silently ignore
    }
  }

  async function loadSession() {
    if (streaming) return;
    const id = sessionInput.trim();
    if (!id) return;
    setSessionError(null);
    try {
      const res = await fetch(`${API}/history/${id}`);
      if (!res.ok) {
        setSessionError("Session nicht gefunden");
        return;
      }
      const history: { role: "user" | "assistant"; content: string }[] =
        await res.json();
      localStorage.setItem("session_id", id);
      setSessionId(id);
      setMessages(history.map((m) => ({ role: m.role, content: m.content })));
      setShowSessionInput(false);
      setSessionInput("");
    } catch {
      setSessionError("Verbindungsfehler");
    }
  }

  async function send() {
    if (!input.trim() || streaming || !sessionId) return;
    const question = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    setStreaming(true);

    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, session_id: sessionId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { role: "assistant", content: `Fehler: ${err.detail ?? "Unbekannter Fehler"}` },
        ]);
        return;
      }

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
    } catch {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", content: "Verbindungsfehler: Backend nicht erreichbar." },
      ]);
    } finally {
      setStreaming(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div
      className="flex flex-col h-screen"
      style={{ background: "var(--bg)", color: "var(--text)", position: "relative", zIndex: 1 }}
    >
      {/* Header */}
      <header
        style={{
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-surface)",
          backdropFilter: "blur(8px)",
        }}
        className="flex items-center justify-between px-6 py-4 shrink-0"
      >
        <div className="flex items-center gap-3">
          <span style={{ color: "var(--gold)", opacity: 0.8 }}>
            <CrossIcon />
          </span>
          <div>
            <h1
              style={{
                fontFamily: "var(--font-serif), Georgia, serif",
                fontSize: "1.2rem",
                fontWeight: 600,
                letterSpacing: "0.08em",
                color: "var(--text)",
              }}
            >
              BIBEL KI
            </h1>
            <p style={{ fontSize: "0.65rem", color: "var(--text-dim)", letterSpacing: "0.12em" }}>
              SCHRIFT · FRAGEN · ANTWORTEN
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Session badge + copy */}
          {sessionId && (
            <div className="flex items-center gap-1">
              <span
                style={{
                  fontFamily: "var(--font-mono, monospace)",
                  fontSize: "0.7rem",
                  color: "var(--text-dim)",
                  letterSpacing: "0.04em",
                  userSelect: "all",
                }}
              >
                {sessionId.slice(0, 8)}…
              </span>
              <button
                onClick={copySessionId}
                title="Session-ID kopieren"
                style={{
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  color: copySuccess ? "var(--gold)" : "var(--text-dim)",
                  padding: "2px 4px",
                  borderRadius: "4px",
                  display: "flex",
                  alignItems: "center",
                  transition: "color 0.15s",
                }}
              >
                {copySuccess ? <CheckIcon /> : <CopyIcon />}
              </button>
            </div>
          )}

          {/* Load session button + expanding input */}
          <div style={{ position: "relative" }}>
            <div className="flex items-center gap-1">
              <button
                onClick={() => {
                  setShowSessionInput((v) => !v);
                  setSessionError(null);
                  setSessionInput("");
                  setTimeout(() => sessionInputRef.current?.focus(), 50);
                }}
                title="Session laden"
                className="flex items-center gap-1 transition-colors"
                style={{
                  fontSize: "0.7rem",
                  letterSpacing: "0.08em",
                  color: showSessionInput ? "var(--gold)" : "var(--text-dim)",
                  border: `1px solid ${showSessionInput ? "var(--gold-dim)" : "var(--border)"}`,
                  borderRadius: "6px",
                  padding: "5px 8px",
                  background: "transparent",
                  cursor: "pointer",
                }}
              >
                <LoadSessionIcon />
              </button>

              {showSessionInput && (
                <div className="flex items-center gap-1">
                  <input
                    ref={sessionInputRef}
                    type="text"
                    value={sessionInput}
                    onChange={(e) => {
                      setSessionInput(e.target.value);
                      setSessionError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") loadSession();
                      if (e.key === "Escape") {
                        setShowSessionInput(false);
                        setSessionInput("");
                        setSessionError(null);
                      }
                    }}
                    placeholder="Session-ID eingeben…"
                    style={{
                      width: "220px",
                      background: "var(--bg-surface-2)",
                      border: `1px solid ${sessionError ? "#c0392b" : "var(--border)"}`,
                      borderRadius: "6px",
                      padding: "5px 10px",
                      fontSize: "0.75rem",
                      color: "var(--text)",
                      outline: "none",
                      fontFamily: "var(--font-mono, monospace)",
                    }}
                  />
                  <button
                    onClick={loadSession}
                    disabled={!sessionInput.trim()}
                    style={{
                      fontSize: "0.7rem",
                      letterSpacing: "0.06em",
                      color: sessionInput.trim() ? "var(--gold)" : "var(--text-muted)",
                      border: `1px solid ${sessionInput.trim() ? "var(--gold-dim)" : "var(--border)"}`,
                      borderRadius: "6px",
                      padding: "5px 10px",
                      background: "transparent",
                      cursor: sessionInput.trim() ? "pointer" : "not-allowed",
                    }}
                  >
                    LADEN
                  </button>
                </div>
              )}
            </div>

            {/* Error message */}
            {sessionError && (
              <p
                style={{
                  position: "absolute",
                  top: "calc(100% + 4px)",
                  right: 0,
                  fontSize: "0.7rem",
                  color: "#e74c3c",
                  whiteSpace: "nowrap",
                  background: "var(--bg-surface)",
                  padding: "2px 6px",
                  borderRadius: "4px",
                  border: "1px solid rgba(231,76,60,0.3)",
                }}
              >
                {sessionError}
              </p>
            )}
          </div>

          {/* New chat */}
          <button
            onClick={newChat}
            className="flex items-center gap-2 transition-colors"
            style={{
              fontSize: "0.75rem",
              letterSpacing: "0.08em",
              color: "var(--text-dim)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "6px 12px",
              background: "transparent",
              cursor: "pointer",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = "var(--gold)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--gold-dim)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = "var(--text-dim)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border)";
            }}
          >
            <PlusIcon />
            NEUER CHAT
          </button>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto" style={{ padding: "2rem 1rem" }}>
        <div style={{ maxWidth: "720px", margin: "0 auto" }}>

          {/* Empty state */}
          {messages.length === 0 && (
            <div
              className="flex flex-col items-center justify-center message-animate"
              style={{ paddingTop: "6rem", paddingBottom: "2rem", textAlign: "center" }}
            >
              <div style={{ color: "var(--gold)", opacity: 0.3, marginBottom: "1.5rem" }}>
                <CrossIcon />
              </div>
              <p
                style={{
                  fontFamily: "var(--font-serif), Georgia, serif",
                  fontSize: "1.4rem",
                  fontWeight: 400,
                  fontStyle: "italic",
                  color: "var(--text-dim)",
                  marginBottom: "0.75rem",
                }}
              >
                Was sucht dein Herz in der Schrift?
              </p>
              <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", letterSpacing: "0.1em" }}>
                FRAGE ZU EINEM VERS · THEMA · BUCH DER BIBEL
              </p>
            </div>
          )}

          {/* Message list */}
          <div className="flex flex-col gap-6">
            {messages.map((msg, i) => (
              <div
                key={i}
                className="message-animate"
                style={{
                  display: "flex",
                  justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                }}
              >
                {msg.role === "user" ? (
                  /* User bubble */
                  <div
                    style={{
                      maxWidth: "80%",
                      background: "var(--bg-user)",
                      border: "1px solid var(--border)",
                      borderRadius: "16px 16px 4px 16px",
                      padding: "0.75rem 1.1rem",
                      fontSize: "0.9rem",
                      lineHeight: "1.6",
                      color: "var(--text)",
                    }}
                  >
                    {msg.content}
                  </div>
                ) : (
                  /* Assistant answer */
                  <div
                    style={{
                      width: "100%",
                      paddingLeft: "1.2rem",
                      borderLeft: "2px solid var(--border-gold)",
                    }}
                  >
                    <div className="assistant-markdown">
                      <ReactMarkdown>
                        {msg.content || ""}
                      </ReactMarkdown>
                      {streaming && i === messages.length - 1 && msg.content === "" && (
                        <span className="streaming-cursor" />
                      )}
                      {streaming && i === messages.length - 1 && msg.content !== "" && (
                        <span className="streaming-cursor" />
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div ref={bottomRef} style={{ height: "1px" }} />
        </div>
      </div>

      {/* Input */}
      <div
        style={{
          borderTop: "1px solid var(--border)",
          background: "var(--bg-surface)",
          padding: "1rem",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            maxWidth: "720px",
            margin: "0 auto",
            display: "flex",
            gap: "0.75rem",
            alignItems: "flex-end",
          }}
        >
          <div style={{ flex: 1, position: "relative" }}>
            <textarea
              ref={inputRef}
              rows={1}
              style={{
                width: "100%",
                background: "var(--bg-surface-2)",
                border: "1px solid var(--border)",
                borderRadius: "12px",
                padding: "0.8rem 1rem",
                color: "var(--text)",
                fontSize: "0.9rem",
                lineHeight: "1.5",
                outline: "none",
                resize: "none",
                fontFamily: "var(--font-sans), system-ui, sans-serif",
                transition: "border-color 0.15s",
                opacity: streaming ? 0.5 : 1,
                overflowY: "hidden",
              }}
              placeholder="z.B. Was bedeutet Johannes 3:16?"
              value={input}
              disabled={streaming}
              onChange={(e) => {
                setInput(e.target.value);
                // Auto-resize
                e.target.style.height = "auto";
                e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
              }}
              onKeyDown={handleKeyDown}
              onFocus={(e) => {
                e.target.style.borderColor = "var(--gold-dim)";
              }}
              onBlur={(e) => {
                e.target.style.borderColor = "var(--border)";
              }}
            />
          </div>

          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            style={{
              background: input.trim() && !streaming ? "var(--gold)" : "var(--bg-surface-2)",
              color: input.trim() && !streaming ? "#0c0b0a" : "var(--text-muted)",
              border: "1px solid",
              borderColor: input.trim() && !streaming ? "var(--gold)" : "var(--border)",
              borderRadius: "12px",
              padding: "0.8rem 1rem",
              cursor: streaming || !input.trim() ? "not-allowed" : "pointer",
              transition: "all 0.15s ease",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              if (!streaming && input.trim()) {
                (e.currentTarget as HTMLButtonElement).style.background = "#e8c870";
              }
            }}
            onMouseLeave={(e) => {
              if (!streaming && input.trim()) {
                (e.currentTarget as HTMLButtonElement).style.background = "var(--gold)";
              }
            }}
          >
            {streaming ? (
              <span style={{ display: "flex", gap: "2px", alignItems: "center" }}>
                {[0, 1, 2].map((n) => (
                  <span
                    key={n}
                    style={{
                      width: "3px",
                      height: "3px",
                      borderRadius: "50%",
                      background: "var(--text-muted)",
                      animation: `cursor-pulse 1s ease-in-out ${n * 0.2}s infinite`,
                    }}
                  />
                ))}
              </span>
            ) : (
              <SendIcon />
            )}
          </button>
        </div>

        <p
          style={{
            textAlign: "center",
            fontSize: "0.65rem",
            color: "var(--text-muted)",
            letterSpacing: "0.08em",
            marginTop: "0.6rem",
          }}
        >
          ENTER zum Senden · SHIFT+ENTER für neue Zeile
        </p>
      </div>
    </div>
  );
}
