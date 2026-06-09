# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Is This

Odysseus — self-hosted AI workspace. Local-first chat, agent with tools, model serving (Cookbook), deep research, documents, memory, email, notes, tasks, calendar. FastAPI backend + vanilla JS frontend, no frontend build step.

## Commands

**Start (Windows):**
```powershell
py -3.11 -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

**Start (Docker):**
```bash
docker compose up -d --build
```

**Tests:**
```bash
python -m pytest                                        # all
python -m pytest tests/path/to/test_file.py            # single file
python -m pytest -m area_security                       # by area
python -m pytest -m "area_routes and sub_chat"          # area + sub
```

**Before committing:**
```bash
python -m py_compile app.py routes/*.py src/*.py        # Python syntax
node --check static/js/<changed-file>.js                # JS syntax
docker compose config                                    # Docker validation
```

**Test taxonomy markers** — `area_*` (security, routes, services, cli, js, helpers, unit) and `sub_*` (auto-generated from test filename).

## Architecture

```
app.py                  FastAPI entry + CORS + middleware
core/                   Auth, DB, constants, models, exceptions, session manager
src/                    AI core — agent loop, tools, LLM interaction, memory, embeddings
routes/                 HTTP endpoint blueprints (chat, session, model, memory, email, etc.)
services/               Business logic (llm_service, cookbook_service, memory_service, etc.)
mcp_servers/            Built-in MCP servers (email, image gen, Playwright browser)
static/                 Vanilla HTML/CSS/JS frontend — no build step
tests/                  pytest suite with taxonomy markers
data/                   Git-ignored: app.db, chroma/, auth.json, settings.json, uploads/
```

**Key layers:**

- **Agent Core** (`src/agent_loop.py`) — ReasoningLoop orchestrates LLM calls, tool invocations, memory retrieval
- **LLM Interaction** (`src/ai_interaction.py`) — Provider abstraction: OpenAI, Ollama, vLLM, SGLang, llama.cpp, OpenRouter, GitHub Copilot
- **Memory** — ChromaDB + fastembed (ONNX) — vector + keyword retrieval, persistent per user
- **Cookbook** — Hardware profiling, model discovery, GGUF/FP8/AWQ quantization, vLLM/llama.cpp serving

## Code Conventions

**Constants** — never hardcode paths or config. Every persisted file has a constant in `src/constants.py` (e.g. `AUTH_FILE`, `SETTINGS_FILE`, `CHROMA_DIR`). Import and use the constant.

**Internal API calls** — use `internal_api_base()` from `src.constants` instead of hardcoding `http://localhost:7000`.

**Commits** — Conventional Commits: `type(scope): summary`. Types: `fix`, `feat`, `refactor`, `docs`, `test`, `chore`, `ci`.

**Visual style** — dark theme; use CSS variables (`--red`, `--fg`, `--bg`, `--card`, `--border`); no Unicode emoji (use SVG or plain text); monospaced font (Fira Code); reuse existing button/input/card/border classes.

**PRs** — open against `dev` branch. One bug fix or feature per PR. UI changes need desktop + mobile screenshots.

## Stack

Python 3.11+, FastAPI, uvicorn, SQLAlchemy, Pydantic v2, SQLite, ChromaDB, fastembed, httpx, BeautifulSoup4, nh3 (HTML sanitizer), vanilla JS.

## Key Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `APP_BIND` | `127.0.0.1` | Bind address |
| `APP_PORT` | `7000` | Port |
| `AUTH_ENABLED` | `true` | Require login |
| `LOCALHOST_BYPASS` | `false` | Dev auth bypass for loopback |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLite path |
| `ODYSSEUS_DATA_DIR` | `./data` | User data root |
