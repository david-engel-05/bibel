-- Tracks how many messages the current summary covers.
-- Used to avoid re-summarizing on every request — only runs when
-- at least SUMMARY_BATCH_SIZE new messages have accumulated beyond the last summary.
ALTER TABLE chat_sessions
  ADD COLUMN IF NOT EXISTS summary_upto_count INT NOT NULL DEFAULT 0;
