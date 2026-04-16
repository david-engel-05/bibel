# Performance Tuning — Design Spec

**Datum:** 2026-04-16
**Ziel:** Mac-Lüfter beim Betrieb von Bibel KI reduzieren, ohne Antwortqualität zu verschlechtern.

## Kontext

Der M4 Pro löst den Lüfter primär durch zwei back-to-back Ollama-Aufrufe aus:

1. **Hauptantwort** (`gemma4:26b`, stream=True) — Fan startet
2. **Hintergrund-Summary** (`gemma4:26b`, stream=False) — Fan läuft weiter / intensiviert sich, da das Modell sofort erneut geladen wird

Das Kontext-Fenster (`num_ctx`) ist der wichtigste GPU-Last-Faktor; Ollama nutzt standardmäßig 8192+ Tokens.

## Lösung

Drei kombinierte Maßnahmen, alle in `backend/main.py`:

### 1. Separates Summary-Modell

```python
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gemma3:4b")
```

`_maybe_summarize` verwendet `SUMMARY_MODEL` statt `CHAT_MODEL`. Da die Zusammenfassung ein internes Kontextwerkzeug ist (nie direkt sichtbar), ist `gemma3:4b` ausreichend.

### 2. Verzögerung vor Summarisierung

In `save_and_maybe_summarize` wird `time.sleep(5)` vor `_maybe_summarize` eingefügt. Gibt dem M4 Pro 5 Sekunden zwischen Hauptantwort und Summary-Aufruf.

### 3. Ollama-Optionen für Haupt-Chat und Summary

Neue Env-Variablen mit Defaults:
- `CHAT_NUM_CTX=3072` — reduziert GPU-Speicherbedarf pro Token gegenüber Default (~8192)
- `CHAT_NUM_PREDICT=600` — verhindert endlose Generierung

Diese Optionen werden an beide `ollama.chat()`-Aufrufe übergeben (generate() und _maybe_summarize()).

## Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `backend/main.py` | Neue Konstanten, `options`-Parameter, `time.sleep`, `SUMMARY_MODEL` |
| `backend/tests/test_endpoints.py` | Summary-Test prüft `SUMMARY_MODEL` statt `CHAT_MODEL` |

## Konfiguration (`.env`)

```env
SUMMARY_MODEL=gemma3:4b     # kleines Modell für interne Zusammenfassung
CHAT_NUM_CTX=3072            # Kontext-Fenster (Standard Ollama: ~8192)
CHAT_NUM_PREDICT=600         # max. Tokens pro Antwort
```

Einmalig erforderlich: `ollama pull gemma3:4b`

## Was sich nicht ändert

- `CHAT_MODEL` bleibt `gemma4:26b` für alle Nutzerantworten
- Summary-Logik (`_maybe_summarize`, `SUMMARY_THRESHOLD`, `SUMMARY_BATCH_SIZE`) unverändert
- Frontend unberührt
- Alle bestehenden Tests bleiben grün (Mock-Anpassung für SUMMARY_MODEL)

## Nicht im Scope

- Modellwechsel für Hauptantworten
- Frontend-Performance
- Embedding-Caching
