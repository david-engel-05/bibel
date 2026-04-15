-- Add rolling summary column to chat_sessions.
-- The summary is populated by the backend after long conversations
-- and replaces older raw messages in the Ollama context window.
ALTER TABLE chat_sessions
  ADD COLUMN IF NOT EXISTS summary TEXT;
