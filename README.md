# Auyan Platform

AI-native BPO platform for CX support, verticalized for ecommerce.

<img width="256" height="256" alt="auyan-logo" src="https://github.com/user-attachments/assets/391ab22d-f03f-43c7-97e7-5ebf0bf5ba84" />

## Architecture

Monorepo with three apps and a shared package:

| Directory | Description | Stack |
|-----------|-------------|-------|
| `apps/api` | Backend — FastAPI, LangGraph agent, webhooks | Python 3.11+, Poetry |
| `apps/web` | Dashboard — internal inbox + client portal | Next.js 15, TypeScript |
| `apps/widget` | Embeddable chat widget (WIP) | TypeScript |
| `packages/shared` | Shared types and utilities | TypeScript |
| `supabase/` | Database migrations and seed data | SQL |
| `docs/` | Technical documentation | Markdown |

### Agent flow

```
Ticket in → Identify tenant → Load context + KB (RAG)
  → Classify intent (AOP selection) → Reason (Claude)
  → Execute skill / Respond / Escalate to human
  → Full trace logged to Langfuse
```

Key capabilities:
- **Multi-tenant**: every table scoped by `tenant_id`, RLS enforced, GUC-scoped connections
- **Supervisor pattern**: L2/L3 skills require supervisor approval before execution
- **Shopify skills**: order lookup, cancellations, refunds, returns, address changes
- **Observability**: full Langfuse traces per conversation (reasoning, tool calls, decisions)
- **Rate limiting + budget caps**: per-tenant and per-customer rate limits, daily spend caps

## Prerequisites

- Python 3.11+ (for `apps/api`)
- Node.js 22+ (for `apps/web`)
- [pnpm](https://pnpm.io/) 11+ (package manager for Node apps)
- [Poetry](https://python-poetry.org/) 1.8+ (package manager for Python)
- A [Supabase](https://supabase.com/) project (Postgres + pgvector)
- API keys: Anthropic (agent), OpenAI (embeddings), Langfuse (observability)

## Getting started

### 1. Clone and configure environment

```bash
git clone https://github.com/Auyan-ai/platform.git
cd platform
cp .env.example .env
# Fill in the values in .env — see comments in .env.example for guidance
```

### 2. Install dependencies

```bash
# Backend
cd apps/api
poetry install
cd ../..

# Frontend + shared packages
pnpm install
```

### 3. Apply database migrations

Apply migrations to your Supabase project in order. You can use the Supabase CLI
or run the SQL files manually via the Supabase dashboard SQL editor:

```bash
# If using Supabase CLI:
supabase db push
```

Optionally seed the database with test data:

```bash
cd apps/api
poetry run python -m scripts.seed_kb --clear
```

### 4. Run locally

```bash
# Terminal 1 — API
cd apps/api
poetry run uvicorn apps.api.main:app --reload --port 8000

# Terminal 2 — Web dashboard
pnpm dev:web
```

- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Web dashboard: http://localhost:3000

### Docker (API only)

```bash
docker compose up
```

This starts the API on port 8000 with a Redis sidecar.

## Running tests

```bash
# Backend — lint + tests
cd apps/api
poetry run ruff check .
poetry run pytest --tb=short -q

# Frontend — typecheck
pnpm typecheck
```

## Deploy

The platform deploys to [Railway](https://railway.app/):

- **API**: builds from the root `Dockerfile`, serves on `$PORT`
- **Web**: standard Next.js build (`pnpm build:web`)

Environment variables are managed in Railway's dashboard. See `.env.example` for
the full list of required variables.

## Branch workflow

| Branch | Purpose |
|--------|---------|
| `main` | Production — only receives merges from `develop` |
| `develop` | Staging — all work integrates here first |
| `feature/*`, `fix/*` | Work branches — PR against `develop` |

Commit format: `feat:`, `fix:`, `chore:`, `docs:`

## Documentation

- [Architecture — Agent v2](docs/architecture-agent-v2.md)
- [Architecture — Web](docs/architecture-web.md)
- [Progress log](docs/progress.md)
- [Project rules](CLAUDE.md)
