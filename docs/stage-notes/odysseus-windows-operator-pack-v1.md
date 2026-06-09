# Stage: odysseus-windows-operator-pack-v1

Add a small Windows operator pack for Bujar's local Odysseus hardening fork.
This stage is ops convenience only; it changes no application behavior,
guardrail code, remotes, or packaging workflow.

## Scripts

- `tools/odysseus-status.ps1` - one-command workspace, branch, remote, helper,
  venv, process, and port visibility.
- `tools/run-guard-tests.ps1` - one-command targeted guardrail validation.

## Safety checks

`odysseus-status.ps1` shows the current branch, `git status --short`, latest
six commits, remotes, whether both `origin` and `mundoin` exist, and a clear
warning that pushes for this branch should go to `mundoin`, not `origin`.

It also reports whether `venv\Scripts\python.exe` exists, lists known local
Windows helpers, checks port 7000 listeners, and searches for uvicorn processes
bound to that port.

## Guard validation command

`run-guard-tests.ps1` runs the guard suites first, then runs the focused agent
operating-rules prompt test separately so `-k` filtering cannot accidentally
filter the guard files.
