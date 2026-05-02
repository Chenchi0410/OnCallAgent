# Project Guidelines

## Code Style
- Language: Python 3.11+.
- Formatting and linting follow `pyproject.toml` tool config (`ruff`, `black`, `isort`).
- Prefer explicit type hints on public functions and service boundaries, but keep strictness practical (project pyright/mypy config is intentionally relaxed).
- Reuse existing patterns from:
  - `app/api/` for route-level error handling and response shape.
  - `app/services/` for business logic orchestration.
  - `app/agent/aiops/` for LangGraph state transitions.
  - `app/utils/logger.py` for logging style.

## Architecture
- Keep boundaries clear:
  - `app/api/`: HTTP layer only (validation, request/response mapping, SSE response).
  - `app/services/`: business workflows and orchestration.
  - `app/agent/`: planning/execution/replanning and MCP tool integration.
  - `app/core/`: infrastructure clients/factories (LLM, Milvus).
  - `app/models/`: Pydantic schemas.
  - `app/tools/`: LangChain tools callable by agents.
- For new functionality, prefer extending `services` and `agent` layers instead of adding logic directly in API routes.
- Preserve app lifecycle behavior in `app/main.py` (Milvus connect on startup, close on shutdown).

## Build and Test
- Preferred local workflow (Linux/macOS):
  - `make format`
  - `make lint`
  - `make test-quick`
  - `make test`
- On Windows, `make` may be unavailable. Use:
  - `start-windows.bat` / `stop-windows.bat` for service orchestration.
  - `.venv\\Scripts\\python -m pytest tests -v` for tests.
- For quick validation after code changes, run the smallest relevant check first (targeted pytest or module-level lint), then broader checks if needed.

## Conventions
- Streaming endpoints must keep SSE event shape stable (`type` + payload fields) to avoid frontend regressions.
- Keep RAG chat history trimming behavior consistent when updating chat flow logic (`app/services/rag_agent_service.py`).
- For MCP interactions, use retry-aware client paths in `app/agent/mcp_client.py`; avoid ad-hoc direct external calls.
- Keep API response contracts backward-compatible with current models in `app/models/request.py` and `app/models/response.py`.

## Docs and References
- Project setup, commands, and API examples: `README.md`.
- MCP tool capabilities and parameters: `mcp_servers/README.md`.
- AIOps troubleshooting knowledge docs: `aiops-docs/*.md`.
- Prefer linking to these docs in discussions/PRs instead of duplicating large instruction blocks.