# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

All commands assume the virtual environment is active (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Linux/macOS).

**Code quality** (Linux/macOS via Makefile, Windows use `python -m` equivalent):
```
make format          # ruff format + isort
make lint            # ruff check
make fix             # ruff check --fix + format
make type-check      # mypy
make security        # bandit
make check-all       # format + lint + test
make pre-commit      # run all pre-commit hooks
```

**Testing** (no tests directory exists yet):
```
make test            # pytest with coverage
make test-quick      # pytest without coverage
make coverage        # generate HTML coverage report
```

**Service management** (Linux/macOS):
```
make up              # start Milvus Docker containers
make down            # stop Milvus Docker containers
make start           # start all services (CLS + Monitor MCP + FastAPI) in background
make stop            # stop all services
make restart         # restart all services
make dev             # FastAPI with hot reload (foreground)
make run             # FastAPI production mode (foreground)
```

**Windows** — `make` is unavailable, use:
```
start-windows.bat    # start all services
stop-windows.bat     # stop all services
python -m uvicorn app.main:app --host 0.0.0.0 --port 9900            # FastAPI
python mcp_servers/cls_server.py                                       # CLS MCP (port 8003)
python mcp_servers/monitor_server.py                                   # Monitor MCP (port 8004)
```

**Docker**:
```
docker compose -f vector-database.yml up -d    # start Milvus + etcd + MinIO + Attu
docker compose -f vector-database.yml down     # stop
```

## Architecture

**Layer boundaries** (top-down, each layer only calls the one below):
- `app/api/` — HTTP only: request validation, SSE response streaming, delegates to services
- `app/services/` — business workflows and orchestration (RAG agent, AIOps diagnosis, vector indexing)
- `app/agent/` — LangGraph state graphs (Plan-Execute-Replan) and MCP tool client management
- `app/core/` — infrastructure: LLM factory, Milvus client (singletons)
- `app/models/` — Pydantic schemas for requests/responses
- `app/tools/` — LangChain `@tool` functions callable by agents

**Two distinct LLM pathways**:
1. **RAG Agent** (`app/services/rag_agent_service.py`) — uses `langchain_qwq.ChatQwen` for direct DashScope Qwen integration. Builds a LangGraph agent via `create_agent()` with tools + MemorySaver checkpointer. Handles both streaming (SSE `messages` mode) and non-streaming chat.
2. **AIOps Diagnosis** (`app/services/aiops_service.py`) — uses `ChatQwen` directly in Planner/Executor/Replanner nodes. The Plan-Execute-Replan workflow is a `StateGraph(PlanExecuteState)` with three nodes and a conditional edge on Replanner (continue → Executor, respond → END).

**MCP integration** (`app/agent/mcp_client.py`):
- Global singleton `MultiServerMCPClient` with exponential-backoff retry interceptor (3 retries, 1s base delay)
- Servers configured from `.env`: CLS (port 8003), Monitor (port 8004), Chrome CDP (port 8005, optional, disabled by default)
- Both RAG agent and AIOps agent load MCP tools at initialization time
- If MCP services are unavailable, agents gracefully degrade to local tools only

**Vector store** (`app/services/vector_*.py`):
- Milvus standalone via Docker Compose (`vector-database.yml`)
- Collection `biz` with 1024-dim float vectors, L2 metric, IVF_FLAT index
- Embedding model: DashScope `text-embedding-v4` (1024-dim)
- Document upload auto-indexes via `vector_index_service.index_single_file()`
- RAG retrieval uses `vector_store_manager` → LangChain Milvus retriever with configurable `RAG_TOP_K` (default 3)

**Session management**:
- In-memory `MemorySaver` checkpointer shared across both RAG agent and AIOps service
- Sessions keyed by `thread_id` (passed as `session_id` from API)
- `trim_messages_middleware` exists in `rag_agent_service.py` but is **not wired in** — it's dead code (see `learnszs.md`)

## Key Constraints

- **SSE event shapes must remain stable** — the frontend at `static/app.js` expects specific `type` + payload fields. Do not rename or restructure SSE event types without updating the frontend.
- **API response contracts** in `app/models/request.py` and `app/models/response.py` must stay backward-compatible.
- **MCP interactions** must go through `app/agent/mcp_client.py` retry-aware paths; never make ad-hoc direct external calls.
- **Milvus connection lifecycle** is managed in `app/main.py` lifespan (connect on startup, close on shutdown).
- **`.env` contains live API keys** — never commit it. The `.gitignore` already excludes it.
- **No tests directory exists** — test commands in Makefile/pyproject.toml reference `tests/` but it hasn't been created yet.

## Config

All configuration via `.env` → `app/config.py` (Pydantic `BaseSettings`). Key settings:
- `DASHSCOPE_API_KEY` / `DASHSCOPE_MODEL` / `DASHSCOPE_EMBEDDING_MODEL` — LLM and embedding model selection
- `MILVUS_HOST` / `MILVUS_PORT` — vector database connection
- `RAG_TOP_K` — number of retrieved documents (default 3)
- `CHUNK_MAX_SIZE` / `CHUNK_OVERLAP` — document splitting parameters
- `MCP_CLS_URL` / `MCP_MONITOR_URL` / `MCP_CHROME_ENABLED` — MCP server endpoints
- `RAG_MODEL` — model used by both RAG agent and AIOps nodes (default `qwen3-8b`)

## Code Quality Tooling

- **Formatter**: ruff (primary), black (fallback in Makefile) — line length 100
- **Linter**: ruff with rules E, W, F, I, C, B, UP
- **Type checker**: mypy and pyright (both configured with relaxed strictness; ignore missing imports for `dashscope`, `langchain`, `pymilvus`)
- **Security**: bandit
- **Pre-commit**: trailing-whitespace, end-of-file-fixer, isort, black, ruff, bandit, docformatter, mdformat, commitizen
