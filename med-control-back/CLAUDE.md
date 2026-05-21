# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MedAI is a conversational AI assistant specialized in medication adherence. It helps users manage medication schedules, parse prescriptions, and create reminders via n8n. The system runs as both a CLI tool and a FastAPI web service.

## Development Commands

```bash
source .venv/bin/activate              # Activate virtual environment (Python 3.12.3)
python main.py                         # Run the CLI assistant
uvicorn api.main:app --reload          # Run the FastAPI server (port 8000)
docker compose up -d                   # Start Supabase stack + n8n (PostgreSQL, Storage, Studio, Kong, etc.)
```

To exit the CLI: type `salir`, `exit`, or `quit`. Toggle voice mode in CLI: `/voice`.

Supabase Studio is available at `http://localhost:3000` after `docker compose up`.

No build system, test runner, or lint CLI is configured. Ruff is available via VS Code on save.

## Architecture

### Dual entry points

- **`main.py`** — CLI entry point. Instantiates `Agent(session_id="default", user_id=TEST_USER_ID)` and calls `.run()`. `TEST_USER_ID = "11111111-1111-1111-1111-111111111111"` (seed user). Must remain functional at all times.
- **`api/main.py`** — FastAPI entry point. Loads `.env`, sets up CORS, initializes Supabase client + Storage bucket on startup, and mounts routers from `api/routes/`.

### Core agent (`core/llm.py`)

`Agent` is the central component. Key design points:
- Multi-session: constructed with `session_id` and optional `user_id`; history persisted to `historiales/{session_id}.json` (CLI) and to the `messages` table via `db.save_message()` (API).
- `user_id` is separate from `session_id` — do not derive one from the other. Pass both explicitly.
- Provider-agnostic: delegates all LLM calls to `self.provider` (a `BaseProvider`).
- `chat_stream()` is the primary async generator — yields string tokens and handles tool call dispatch recursively.
- `chat()` (sync, CLI-only) uses a persistent `self._loop` (not `asyncio.run()`) to avoid closing the loop between turns.
- STT and TTS are lazy properties — only instantiated when voice mode is activated.
- System prompt defines a medical assistant persona (professional, empathetic, Markdown-heavy) including instructions for all 7 tools and recurrence parameter usage.
- `_user_id_tools = ("create_reminder", "list_reminders", "delete_reminders", "search_knowledge_base", "update_reminder")` — `user_id` is injected automatically into these tools before dispatch; do not rely on the model to pass it.

### Provider abstraction (`core/providers/`)

All LLM backends implement `BaseProvider` (abstract, `core/providers/base.py`):
- Single abstract method: `async stream(messages, tools) -> AsyncGenerator[dict, None]`
- Yields `{"type": "token", "content": str}` or `{"type": "tool_calls", "calls": [...]}`

Available providers (registered in `core/providers/__init__.py`):
- `OllamaProvider` — always available; uses `AsyncClient` from `ollama`.
- `AnthropicProvider` — conditionally imported; normalizes the shared message format to Anthropic's API. Requires `anthropic` installed manually (not in `requirements.txt`).

Active provider selected via `LLM_PROVIDER` env var (default: `ollama`). `create_provider()` handles env-based configuration.

### Supabase client (`core/supabase_client.py`)

Singleton async client for all Supabase operations. Replaces asyncpg.

- `init_supabase_client()` — async, called once in FastAPI `startup` event. Reads `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`.
- `close_supabase_client()` — called in FastAPI `shutdown` event.
- `get_supabase()` — synchronous getter for use inside request handlers (after startup).
- `create_temp_client()` — creates a fresh client safe for use inside `ThreadPoolExecutor` (avoids sharing the singleton's event loop). Used by tools that call the DB from a worker thread.

### Storage (`core/storage.py`)

Manages the `prescriptions` bucket in Supabase Storage.

- `ensure_bucket_exists()` — called in FastAPI startup; creates the bucket if it doesn't exist.
- `upload_prescription(user_id, filename, file_bytes, content_type)` → storage path string.
- `get_prescription_url(path)` → signed URL valid for 1 hour.

### OCR pipeline (`core/ocr.py`)

Processes prescription images and PDFs to extract structured medication data.

**Data models**:
- `PrescriptionData` — fields: `medication`, `dose`, `frequency`, `duration`, `prescribing_doctor`, `raw_notes`.
- `OCRResult` — contains `raw_text` (str) + `structured` (PrescriptionData).

**Pipeline** (called by `process_prescription(file_bytes, content_type)`):
Sends the image or PDF directly to Claude vision (`claude-haiku-4-5-20251001` by default, overridable via `ANTHROPIC_FAST_MODEL`). No system packages required — no Tesseract, no Poppler.
- Images (JPEG/PNG/WEBP): sent as `image` content block.
- PDFs: sent as `document` content block (native Anthropic PDF support).
- Returns `OCRResult` with `raw_text` (full extracted text) + `structured` (`PrescriptionData`).

### Embeddings / RAG (`core/embeddings.py`)

Generates and stores semantic embeddings for uploaded documents.

- `chunk_text(text)` — splits text into chunks of ~500 chars with 50-char overlap.
- `_embed(text)` — calls Voyage AI `voyage-3-lite` via `voyageai.Client`; returns a 512-dim float list. Requires `VOYAGE_API_KEY`.
- `generate_and_save_embeddings(document_id, user_id, text)` — chunks text, embeds each chunk, persists to `document_embeddings` via `db.save_document_embedding()`. Returns chunk count.

Similarity search is done by `db.search_similar_chunks(user_id, query_embedding, top_k=3)` using pgvector's cosine distance index.

### Tools (`core/tools.py`)

- `TOOLS` — list of tool schemas in OpenAI function-calling format.
- `_REGISTRY` — dict mapping tool names to Python callables.
- `dispatch(name, args)` — called by `Agent.chat_stream()` after tool_calls events.

**Current tools (7 total)**:

1. **`get_current_datetime()`** — returns current ISO datetime + timezone.

2. **`create_reminder(medication, schedule, dose, notes, user_id, recurrence_type?, recurrence_days?, recurrence_end_date?)`** — fan-out: fetches active channels via `_fetch_notification_channels` (own `create_temp_client()` in `ThreadPoolExecutor`), then POSTs one n8n request per schedule-time × channel combination. Supports full recurrence: `daily`, `weekdays`, `weekends`, `weekly` (with `recurrence_days`), `monthly`, `interval_days`, `interval_hours`. `recurrence_end_date` is required when recurrence is set. Each n8n call shares the same `reminder_id`. WebPush is always included.

3. **`list_reminders(status?, date?, medication?, user_id)`** — calls Supabase RPC `get_user_reminders_grouped` with optional filters.

4. **`delete_reminders(reminder_ids[], user_id)`** — deletes rows from `reminders` table matching the given reminder_id list for the user.

5. **`update_reminder(reminder_id, user_id, medication?, schedule?, message?, notes?)`** — updates one or more fields on an existing reminder row.

6. **`search_knowledge_base(query, user_id)`** — embeds the query via Voyage AI `voyage-3-lite`, then calls `db.search_similar_chunks()` to find the top-3 most similar document chunks from the user's uploaded documents.

7. **`web_search(query)`** — calls Tavily API (`TAVILY_API_KEY`); returns top-3 results with title, content snippet, and URL.

Tools 2–6 have `user_id` injected automatically by `Agent` before dispatch (see `_user_id_tools`).

To add a tool: implement the function, add its schema to `TOOLS`, register it in `_REGISTRY`, and add it to `_user_id_tools` if it needs `user_id`.

### FastAPI backend (`api/`)

- **`api/main.py`** — app factory; CORS middleware; `X-Request-Time` header middleware; startup/shutdown lifecycle for Supabase; `/health` endpoint returns `{status, provider, supabase}`.
- **`api/deps.py`** — `session_store: dict[str, Agent]` (in-memory); `get_or_create_agent(session_id)` factory; `validate_token()` / `get_current_user()` for JWT auth (Bearer token).
- **`api/routes/chat.py`** — `WS /ws/chat`: accepts a WebSocket, streams tokens back with `[DONE]` sentinel. Persists messages via `db.save_message()`.
- **`api/routes/sessions.py`** — session history and management endpoints under `/api/sessions/`.
- **`api/routes/webhooks.py`** — `POST /webhooks/n8n`: receives n8n callbacks; calls `update_reminder_status`. Authenticated via `X-Api-Key` header matching `WEBHOOK_SECRET`.
- **`api/routes/channels.py`** — notification channel management under `/api/users/{user_id}/channels/`. Telegram channels verified via Bot API at save time. Includes `PATCH .../toggle-reminders` and `POST .../set-primary` endpoints.
- **`api/routes/reminders.py`** — `GET /api/users/{user_id}/reminders?status=&date=&medication=` — list and filter user reminders.
- **`api/routes/documents.py`** — `POST /api/users/{user_id}/documents` (upload JPEG/PNG/WEBP/PDF, max 10 MB); `GET /api/users/{user_id}/documents`. Upload triggers a background task: upload to Storage → OCR → embed → persist to `documents` + `document_embeddings`.
- **`api/routes/auth.py`** — authentication endpoints under `/api/auth/`. All require `X-Auth-Secret` header matching `AUTH_SECRET_INTERNAL`:
  - `POST /api/auth/oauth-user` — find-or-create user by email (Google / OAuth flows).
  - `POST /api/auth/register` — register with email + password (bcrypt hash stored).
  - `POST /api/auth/login` — validate credentials; returns `{id, role}`.
- **`api/models.py`** — Pydantic schemas (`ChatRequest`, `ChatResponse`, etc.).

### Database (`core/db.py` + `database/init.sql`)

Supabase Python SDK (`supabase>=2.10.0`) with async client. Functions use `client.table()`, `client.rpc()`, and `client.from_()`.

Key functions:
- `get_notification_channels(user_id)` — returns verified channels with `receive_reminders=True`.
- `upsert_user_channel(...)` — inserts or updates a notification channel.
- `update_reminder_status(reminder_id, status, error_message?)` — updates reminder row status.
- `create_document(user_id, filename, ...)` — inserts a document record.
- `update_document_processing(document_id, extracted_text, chunk_count)` — marks document as processed.
- `save_document_embedding(document_id, user_id, chunk_text, chunk_index, embedding)` — persists a single chunk + its 768-dim vector.
- `search_similar_chunks(user_id, query_embedding, top_k)` — pgvector cosine similarity search over `document_embeddings`.
- `get_user_documents(user_id)` — list documents for a user.
- `save_message(session_id, role, content, tool_calls?)` — persist chat turn to `messages` table.

Key schema points (`database/init.sql`):
- Extensions: `uuid-ossp`, `vector` (pgvector).
- `reminders`: `UNIQUE (reminder_id, channel)` — one row per channel per reminder (fan-out).
- `user_channels`: `receive_reminders BOOLEAN DEFAULT true` — per-channel opt-out; `is_primary BOOLEAN`.
- `reminder_status` enum: `scheduled`, `firing`, `completed`, `failed`, `cancelled`.
- `channel_type` enum: `telegram`, `email`, `discord`, `webpush`, `sms`.
- `message_role` enum: `system`, `user`, `assistant`, `tool`.
- `document_type` enum: `prescription`, `medical_plan`, `lab_results`, `other`.
- `messages` table: `session_id`, `role`, `content`, `tool_calls` (JSONB), `sequence_num` (unique per session). Replaces `historiales/*.json` for API sessions.
- `documents` table: `user_id`, `filename`, `file_type`, `document_type`, `file_path`, `file_size`, `extracted_text`, `processed`, `embeddings_generated`, `chunk_count`.
- `document_embeddings` table: `document_id`, `user_id`, `chunk_text`, `chunk_index`, `embedding` (vector 512), `metadata`. IVFFlat index for fast similarity search.

### n8n workflow (`n8n-workflow.json`)

Published webhook at `N8N_WEBHOOK_URL`. Flow:

```
Webhook Entry → Normalize Input (Set v3) → Save to Database (CTE executeQuery)
  → Respond 200 OK → Generate .ics File → Wait Until Scheduled Time
  → Update Status → Firing → Switch Channel
  → [Telegram / Attach .ics to Email → Email / Discord / WebPush]
  → Callback to Backend → Update Status → Completed
```

Key implementation details:
- **Normalize Input**: Set node v3.3 using `assignments` format (not `values.string`).
- **Save to Database**: `executeQuery` with CTE — INSERT uses subquery `(SELECT id FROM sessions WHERE session_id = ...)` to resolve session FK, then SELECT returns all fields so downstream nodes receive `$json.field` correctly.
- **ON CONFLICT**: `(reminder_id, channel)` — matches the composite unique constraint.
- **Update Status nodes**: `executeQuery` with explicit SQL (`WHERE reminder_id = '{{ $json.reminder_id }}'`).
- **Attach .ics to Email / Telegram**: Code nodes that re-inject binary from `$('Generate .ics File').first().binary.ics` (binary is lost after executeQuery nodes).

n8n runs as a service inside docker-compose (not a standalone container). Import `n8n-workflow.json` manually via the n8n UI after changes.

### Speech modules

- **`core/stt.py`** — `STT` class using `faster_whisper` (`larger-v3`, CUDA/float16, Spanish).
- **`core/tts.py`** — `TTS` class using Kokoro ONNX (`models/kokoro-v1.0.onnx`, voice `ef_dora`, 44.1kHz output).
- Both are lazy-loaded by `Agent` only when voice mode is active.
- These modules are **not in `requirements.txt`** — they require manual installation of `faster_whisper`, `kokoro_onnx`, `sounddevice`, `soundfile`, `torch`, and `onnxruntime`, plus a CUDA-capable GPU.

## Environment Variables

```env
LLM_PROVIDER=anthropic            # anthropic | ollama (default: anthropic)
LLM_MODEL=claude-sonnet-4-6       # overrides provider default
ANTHROPIC_API_KEY=sk-ant-...      # required
ANTHROPIC_FAST_MODEL=claude-haiku-4-5-20251001  # used for OCR; overrides fast model

VOYAGE_API_KEY=...                # required for embeddings (voyage-3-lite)

SUPABASE_URL=https://...supabase.co          # Supabase Cloud project URL
SUPABASE_SERVICE_ROLE_KEY=...               # Service role key (from Supabase Cloud dashboard)

N8N_WEBHOOK_URL=http://localhost:5678/webhook/medai-reminder  # production URL (not /webhook-test/)
WEBHOOK_SECRET=...                # used by n8n Callback to Backend as X-Api-Key

TAVILY_API_KEY=...                # For web_search tool (Tavily web search API)

AUTH_SECRET_INTERNAL=...          # Validates X-Auth-Secret header on /api/auth/ endpoints
ONESIGNAL_APP_ID=...              # optional, for WebPush via OneSignal

CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

## Key Dependencies

Installed in `.venv/` (see `requirements.txt`):
- `supabase>=2.10.0` — async Supabase SDK for all DB and Storage access
- `anthropic>=0.50.0` — LLM provider + OCR via Claude vision
- `voyageai>=0.3.2` — embeddings via `voyage-3-lite` (512-dim)
- `fastapi==0.109.0`, `uvicorn[standard]`, `python-multipart` — web API and file uploads
- `httpx` — HTTP client
- `python-dotenv` — env loading
- `structlog==24.1.0` — structured logging
- `pydantic==2.10.0`, `pydantic-settings==2.1.0` — validation and config
- `tavily-python==0.3.3` — Tavily web search API client
- `PyJWT==2.12.1` — JWT token validation
- `bcrypt==5.0.0` — password hashing for email/password auth
- `pyfiglet==1.0.2` — CLI banner

**Optional / not in requirements.txt** (install manually for voice mode, requires CUDA GPU):
- `faster_whisper`, `kokoro_onnx`, `sounddevice`, `soundfile`, `torch`, `onnxruntime`

## Notes

- CLI session histories stored as JSON in `historiales/{session_id}.json`. API sessions persist to the `messages` table in Supabase.
- Default LLM provider is `anthropic` — requires `ANTHROPIC_API_KEY`. Ollama is still supported locally via `LLM_PROVIDER=ollama`.
- `api/` adds the project root to `sys.path` in `api/main.py` to allow importing `core`.
- DB seed user: `id = 11111111-1111-1111-1111-111111111111`, session `id = 22222222-...`, `session_id = "default"`.
- Supabase Cloud is used in production. For local dev, a self-hosted Supabase stack can run via docker-compose.
- OCR has no OS-level dependencies — Claude vision handles images and PDFs natively.

## Roadmap (pending work)

1. **OneSignal WebPush** — integration node exists in n8n workflow but needs real credentials (`ONESIGNAL_APP_ID`). Complete the WebPush delivery path end-to-end.

2. **WebSocket authentication** — `WS /ws/chat` accepts a `token` query param but does not enforce JWT validation in the current implementation. Needs a `get_current_user` dependency or equivalent guard before the connection is accepted.

3. **n8n notifications** — currently disabled (`_insert_all_reminders_local` bypasses n8n). Re-enable when n8n is deployed and `N8N_WEBHOOK_URL` is configured.

---

### Previously completed (no longer pending)

- ~~**OCR for prescriptions**~~ — ✅ Implemented in `core/ocr.py` via Claude vision (no Tesseract/Poppler required).
- ~~**Real authentication**~~ — ✅ JWT-based auth in `api/deps.py`; registration/login/OAuth endpoints in `api/routes/auth.py`.
- ~~**Agent tools: `list_reminders` / `delete_reminders`**~~ — ✅ Implemented, plus `update_reminder` and `search_knowledge_base` and `web_search`.
- ~~**Next.js frontend**~~ — ✅ Deployed in `med-control-front/`: chat, dashboard, calendar, settings, family.
