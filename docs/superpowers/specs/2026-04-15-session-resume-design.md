# Session Resume — Design Spec

**Date:** 2026-04-15  
**Status:** Approved  

## Goal

Allow users to copy their current session ID and paste a previous session ID to resume an old conversation.

## Scope

Frontend only (`frontend/app/page.tsx`). No backend changes, no routing changes.

---

## UI — Header Changes

The right side of the header gains two new elements between the title and the "NEUER CHAT" button:

### 1. Session-ID Badge + Copy Button

- Displays the first 8 characters of the current session UUID in monospace, e.g. `f47ac10b…`
- A copy icon sits immediately to the right
- **On click:** copies the full UUID to the clipboard; icon swaps to a checkmark for 1.5 seconds ("Kopiert!"), then reverts
- Only rendered once `sessionId` is non-null

### 2. Load-Session Button + Inline Input

- A small "load" icon button (e.g. an arrow-into-box or download arrow)
- **On click:** an inline text input expands to the right of the icon
- Input placeholder: `Session-ID eingeben…`
- A "Laden" confirm button appears next to the input (disabled while input is empty or malformed)
- **Escape key or clicking outside:** collapses the input without doing anything
- Rendered next to the badge at all times; input is hidden by default

### Layout (right side of header, left to right)

```
[f47ac10b… 📋]  [↓]  [+ NEUER CHAT]
                  ↓ expanded:
[f47ac10b… 📋]  [↓] [________________ input ___][Laden]  [+ NEUER CHAT]
```

---

## Behaviour

### Copy flow
1. User clicks copy icon
2. `navigator.clipboard.writeText(sessionId)` is called
3. `copySuccess` state → true for 1500 ms, then false
4. Icon shows checkmark during that window

### Load flow
1. User clicks load icon → `showSessionInput` state → true
2. User types/pastes UUID into input → stored in `sessionInput` state
3. "Laden" button enabled when `sessionInput.trim()` is non-empty
4. User clicks "Laden" or presses Enter:
   a. Call `GET /history/{sessionInput.trim()}`
   b. **404:** set `sessionError` = "Session nicht gefunden", keep input open
   c. **Network error:** set `sessionError` = "Verbindungsfehler"
   d. **Success:** 
      - `localStorage.setItem("session_id", sessionInput.trim())`
      - `setSessionId(sessionInput.trim())`
      - `setMessages(history)`
      - `setShowSessionInput(false)`
      - `setSessionInput("")`
      - `setSessionError(null)`
5. Escape key → `showSessionInput(false)`, clear input and error

### Validation
- "Laden" button is disabled when `sessionInput.trim()` is empty
- No client-side UUID format validation (server returns 404 for invalid IDs anyway)

---

## State

Four new state variables added to the `Home` component:

| Variable | Type | Purpose |
|---|---|---|
| `showSessionInput` | `boolean` | Whether the load input is expanded |
| `sessionInput` | `string` | Current value in the session input field |
| `sessionError` | `string \| null` | Inline error message below the input |
| `copySuccess` | `boolean` | Drives the copy-icon checkmark animation |

---

## Error States

| Scenario | Display |
|---|---|
| 404 from `/history` | Small red text below the input: "Session nicht gefunden" |
| Network error | Small red text below the input: "Verbindungsfehler" |
| Empty input | "Laden" button disabled, no error shown |

---

## Files Changed

| File | Change |
|---|---|
| `frontend/app/page.tsx` | Add 4 state vars, copy handler, load handler, header JSX changes |

No other files are modified.
