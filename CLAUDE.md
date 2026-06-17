# CLAUDE.md

## Purpose

This file is the persistent project memory for Claude in this repo. Keep it
short, current, and focused on durable rules and repo-specific facts.

## Repo Path

`/home/bujar/Repos/odysseus`

## Alignment

- Read `AGENTS.md` first.
- Bujar is the product owner and sole commit/push authority.
- No commit or push unless Bujar explicitly asks.
- OpenCode config is global only at `~/.config/opencode/opencode.jsonc`.
- Do not add repo-local OpenCode config or any `.opencode/` folder.
- Use `ws dev odysseus status`, `check`, `full`, `dev`, `claude`, `codex`,
  and `opencode` when they help with orientation or execution.

## Repo Snapshot

Odysseus is a self-hosted AI workspace:

- local-first chat
- agent with tools
- model serving / Cookbook
- deep research
- documents
- memory
- email
- notes
- tasks
- calendar

Stack:

- FastAPI backend
- vanilla JS frontend
- no frontend build step
- Python 3.11+
- FastAPI, uvicorn, SQLAlchemy, Pydantic v2, SQLite, ChromaDB, fastembed,
  httpx, BeautifulSoup4, nh3

## Architecture

```
app.py                  FastAPI entry + CORS + middleware
core/                   Auth, DB, constants, models, exceptions, session manager
src/                    AI core, agent loop, tools, LLM interaction, memory, embeddings
routes/                 HTTP endpoint blueprints
services/               Business logic
mcp_servers/            Built-in MCP servers
static/                 Vanilla frontend
tests/                  pytest suite
data/                   Git-ignored app/runtime data
```

Key layers:

- Agent Core (`src/agent_loop.py`) - ReasoningLoop orchestrates LLM calls, tool
  invocations, and memory retrieval.
- LLM Interaction (`src/ai_interaction.py`) - provider abstraction for OpenAI,
  Ollama, vLLM, SGLang, llama.cpp, OpenRouter, GitHub Copilot.
- Memory - ChromaDB + fastembed (ONNX), vector + keyword retrieval, persistent
  per user.
- Cookbook - hardware profiling, model discovery, GGUF/FP8/AWQ quantization,
  vLLM/llama.cpp serving.

## Code Conventions

- Never hardcode paths or config. Every persisted file has a constant in
  `src/constants.py` (for example `AUTH_FILE`, `SETTINGS_FILE`, `CHROMA_DIR`).
- Use `internal_api_base()` from `src.constants` instead of hardcoding
  `http://localhost:7000`.
- Keep the visual style dark and consistent with existing button/input/card
  classes.
- Preserve repo-local conventions and avoid broad refactors outside task scope.

## Commands

**Start:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

**Docker:**
```bash
docker compose up -d --build
```

**Tests:**
```bash
python -m pytest
python -m pytest tests/path/to/test_file.py
python -m pytest -m area_security
python -m pytest -m "area_routes and sub_chat"
```

**Before committing:**
```bash
python -m py_compile app.py routes/*.py src/*.py
node --check static/js/<changed-file>.js
docker compose config
```

## Verification

- Provide a way to verify the work: tests, screenshots, analyzer output, or a
  build command.
- Prefer the smallest relevant check over the full suite when possible.
- Run the relevant checks after edits are complete.
- If a check fails, report the failure briefly before trying the next step.

## Output Discipline

- Keep responses concise and factual.
- Say what changed, which files changed, and whether verification passed.
- If blocked, give one sentence on the blocker and stop there.

## Dependency Policy

- Zero new dependencies without Bujar's explicit approval.
- If a library is needed, explain why, how to install it, the risk/weight, and
  an alternative.

## Current Repo Notes

- Keep useful project-specific facts from `README.md`, `ROADMAP.md`, and relevant docs.
- `data/` is git-ignored app/runtime data.
- Historical Windows launcher guidance is obsolete unless legacy Windows
  support is explicitly being restored.
- Treat the repo as local-first and self-hosted unless Bujar explicitly changes
  direction.
