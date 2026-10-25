# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, OpenCode, etc.) working in this repository.
Sub-project details live in `med-control-back/CLAUDE.md` and `med-control-front/AGENTS.md` / `CLAUDE.md`; this file covers the whole monorepo.

## 1. Context and history

This repository started as **J.A.R.V.I.S.**, a personal project to build a general-purpose AI assistant (CLI chat loop, pluggable LLM providers, offline voice with STT/TTS). The first commits (2026-03-21) contain only that assistant.

In May 2026 the assistant was reused for a university project and grew into **MedControl** (a.k.a. MedAI): a medication-adherence assistant with reminders, prescription OCR, RAG over medical documents, multi-channel notifications and a web front-end. Since then almost all work has been MedControl-specific, and the generic assistant is now embedded inside `med-control-back/`.

**Current goal:** resume the personal assistant (Jarvis) as its own product **without breaking MedControl**. MedControl must stay fully functional during and after the separation.

## 2. Repository layout

```
ai-lab/                          (GitHub: XINAD919/J.AR.V.I.S.)
├── med-control-back/            FastAPI API + agent (Python 3.12)
│   ├── main.py                  CLI entry point (Jarvis-style chat loop) — must keep working
│   ├── api/                     FastAPI app, routes, auth deps (MedControl)
│   ├── core/                    Agent, providers, tools, scheduler, OCR, RAG, DB access
│   ├── database/                init.sql + incremental migrations (applied manually)
│   ├── tests/                   pytest suite (scheduler, reminder IDs, update_reminder)
│   ├── n8n-*.json               n8n workflows (reminders, email, WhatsApp/WAHA verification)
│   ├── docker-compose.yml       Full self-hosted Supabase stack + n8n + WAHA
│   └── learning/                Personal learning scratch files (git-ignored)
└── med-control-front/           Next.js (App Router) + NextAuth patient UI
```

## 3. Jarvis vs MedControl boundary

This is the map to use when separating the two products. "Generic" means it has no medical knowledge and could move to Jarvis as-is or with small changes.

| Module (`med-control-back/`) | Owner | Notes |
|---|---|---|
| `core/providers/` (`BaseProvider`, Ollama, Anthropic, `create_provider`) | Jarvis (generic) | Clean port: `stream(messages, tools)` yields token / tool_calls events. |
| `core/stt.py`, `core/tts.py`, `models/` | Jarvis (generic) | faster-whisper + Kokoro ONNX; lazy-loaded voice mode. |
| `main.py` | Jarvis (generic) | CLI loop; currently hard-wired to a MedControl seed user. |
| `core/llm.py` `Agent` | **Mixed — main seam** | Loop, history, compaction and streaming are generic; the system prompt (medical persona), `from core.tools import TOOLS, dispatch` and the hard-coded `_user_id_tools` tuple are MedControl. |
| `core/tools.py` (`TOOLS`, `_REGISTRY`, `dispatch`) | Mixed | `dispatch` and `get_current_datetime`/`web_search` are generic; reminder tools and `search_knowledge_base` are MedControl. |
| `core/embeddings.py`, `core/ocr.py` | MedControl today | RAG/OCR mechanics are reusable, but tied to Supabase tables and `PrescriptionData`. |
| `core/scheduler.py`, `core/recurrence.py`, `core/db.py`, `core/storage.py`, `core/email.py`, `core/supabase_client.py` | MedControl | Reminders, notifications, Supabase. |
| `api/`, `database/`, n8n workflows, `med-control-front/` | MedControl | Product surface. |

**Key coupling to break:** `Agent` imports the medical tool registry and prompt directly. Separation means inverting that dependency: the agent core receives its system prompt and tool registry (and which tools need `user_id`/`session_id` injection) from the outside, and MedControl becomes one *configuration/plugin* of that core.

The separation strategy (separate repo vs. shared package in this monorepo) is **not decided yet** — do not start moving code without an explicit decision recorded here.

## 4. Commands

Backend (`med-control-back/`):

```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8080   # API (README uses 8080; CLAUDE.md mentions 8000)
python main.py                              # CLI assistant; /voice toggles voice mode
docker compose up -d                        # Supabase + n8n + WAHA
python -m pytest -q                         # tests (pytest is NOT installed in .venv yet)
```

Frontend (`med-control-front/`):

```bash
yarn install && yarn dev    # http://localhost:3000
npx tsc --noEmit            # typecheck
```

## 5. Conventions

- **Commits:** Conventional Commits, written in Spanish (match `git log`). No AI attribution / `Co-Authored-By` lines.
- **Code:** identifiers and code comments may be English or Spanish, follow the surrounding file. User-facing strings are Spanish.
- **DB changes:** add a new `database/migration_*.sql` file **and** update `database/init.sql` so fresh installs match migrated ones. Migrations are applied manually with `psql`.
- **Agent tools:** register in `_REGISTRY` and `TOOLS` in `core/tools.py`; if the tool needs the user, add it to `_user_id_tools` in `core/llm.py` (never trust the model to pass `user_id`).
- **CLI must keep working:** `python main.py` is the Jarvis entry point and must not break when changing `Agent`.

## 6. Known gotchas

- `create_provider()` defaults to `anthropic`, but `/health` and docs assume `ollama`. Set `LLM_PROVIDER` explicitly.
- `models/voices-v1.0.bin` and `historial.json` are tracked in git despite `.gitignore` rules (they were committed before the rules existed).
- `docker-compose.yml` sets `N8N_BLOCK_ENV_ACCESS_IN_NODE: "false"` so verification workflows can read `$env.*`; only expose the variables those workflows need.
- Supabase Studio and the Next.js dev server both default to port 3000 — run one on another port.
- Embeddings are `vector(512)` (see `migration_vector_512.sql`); changing the embedding model means a new migration.

## 7. Tooling

- **CodeGraph:** index at `.codegraph/` (git-excluded). Prefer `codegraph_explore` for structural questions; run `codegraph sync -q .` after large edits if the watcher is not running.
- **Engram:** project key resolves to `j.ar.v.i.s.` (from the git remote).
- **Worktrees:** agent worktrees live under `.claude/worktrees/` (git-ignored); remove them once merged.
