# AGENTS.md - Odysseus Repo Policy

## 1. Project Identity

Odysseus is Bujar's self-hosted AI workspace: local-first chat, agent tools,
model serving/Cookbook, deep research, documents, memory, email, notes, tasks,
and calendar. The stack is FastAPI backend + vanilla JS frontend, with no
frontend build step.

Product direction stays local-first and self-hosted unless Bujar explicitly
changes it.

## 2. Current Path and Branch

- Repo path: `/home/bujar/Repos/odysseus`
- Current branch: `bujar-odysseus-hardening`
- Workstation: CachyOS

## 3. Source of Truth / Read Order

1. Read `AGENTS.md`.
2. Read `CLAUDE.md` for Claude-specific repo memory.
3. Read `README.md` for product and implementation summary.
4. Read `ROADMAP.md`, `SECURITY.md`, and `THREAT_MODEL.md` when the task touches product direction, security, or risk.
5. Read source files only after the docs above.

## 4. Agent Operating Rules

- Bujar is the product owner and sole commit/push authority.
- No commit or push unless Bujar explicitly asks.
- OpenCode config is global only at `~/.config/opencode/opencode.jsonc`.
- Do not add repo-local OpenCode config or any `.opencode/` folder.
- Use `AGENTS.md` and `CLAUDE.md` for repo-specific agent instructions.
- Use `ws dev odysseus status`, `check`, `full`, `dev`, `claude`, `codex`,
  and `opencode` where useful.
- Use `.ai-bridge/current-plan.md` and `.ai-bridge/codex-report.md` for Codex
  handoff/report workflow when asked.
- Preserve the existing self-hosted, local-first product direction unless Bujar
  explicitly changes it.
- Keep project-specific facts current in `README.md`, `ROADMAP.md`, or relevant docs
  when work changes the repo state.

## 5. Tooling Contract

- Prefer targeted reads over dumping whole files.
- Inspect `app.py`, `core/`, `src/`, `routes/`, `services/`, `mcp_servers/`,
  `static/`, `tests/`, and `data/` before assuming runtime/build behavior.
- Keep the repo-local constants and internal API rules intact:
  - never hardcode persisted paths or config; use constants from
    `src/constants.py`
  - use `internal_api_base()` from `src.constants` instead of hardcoding
    localhost URLs
- Preserve the existing test commands from `CLAUDE.md` when verifying changes.
- Prefer the smallest relevant check that actually validates the task.

## 6. Git Rules

- No commit unless Bujar explicitly asks.
- No push unless Bujar explicitly asks.
- No branch creation, reset, rebase, clean, or destructive git operation unless
  explicitly requested.
- Keep changes scoped to the files in the task.

## 7. Validation / Check Guidance

- Use `ws dev odysseus status` or `ws dev odysseus check` first when
  orienting.
- Use `ws dev odysseus full` for a broader repo health pass.
- Use `ws dev odysseus dev`, `ws dev odysseus claude`, `ws dev odysseus codex`,
  or `ws dev odysseus opencode` when you need the corresponding helper lane.
- For code or docs changes, run the smallest relevant verification after edits.
- Preserve the current test and build guidance from `CLAUDE.md`:
  - `python -m pytest`
  - `python -m pytest tests/path/to/test_file.py`
  - `python -m pytest -m area_security`
  - `python -m pytest -m "area_routes and sub_chat"`
  - `python -m py_compile app.py routes/*.py src/*.py`
  - `node --check static/js/<changed-file>.js`
  - `docker compose config`

## 8. Repo-Specific Engineering Notes

- Inspect `app.py`, `core/`, `src/`, `routes/`, `services/`, `mcp_servers/`,
  `static/`, `tests/`, and `data/` before assuming runtime or build commands.
- Keep the repo local-first and self-hosted.
- Persisted paths/configs must come from `src/constants.py`.
- Internal API calls must use `internal_api_base()` from `src.constants`.
- Keep the vanilla JS frontend free of a frontend build step unless Bujar
  explicitly changes direction.
- `data/` is git-ignored runtime data.
- Historical Windows launcher guidance is obsolete unless legacy Windows
  support is explicitly being restored.
