# Hermes Executor

Sandboxed terminal/execution service for HuVia agents.

## Purpose

Separates agent reasoning (in `huvia-core`) from command execution. Agents request actions through this service; the service runs them inside ephemeral Docker sandboxes with tiered permissions and human gates.

## Environment variables

Copy `.env.example` to `.env` and fill in:

- `HUVIA_API_KEY` — required shared API key. huvia-core sends this in the `Authorization: Bearer ...` header.
- `SANDBOX_BASE_DIR` — optional absolute base directory for sandbox working directories. Defaults to `/tmp/hermes-sandboxes`.
- `PORT` — optional server port. Defaults to `8000`.

The executor validates that `HUVIA_API_KEY` is configured at startup and rejects unauthenticated requests.

## Permission tiers

| Tier | Allowed operations | Human approval |
|---|---|---|
| `read-only` | Read files, list directories, run non-destructive inspection commands | No |
| `write-code` | Edit files in a sandboxed repo | No (logged) |
| `run-commands` | Execute shell commands in sandbox | No (logged, destructive commands blocked) |
| `deploy-provision` | Create infra, spin up services, register domains | Yes |
| `money-legal` | Money movement, legal filings, binding commitments | Yes |

## API

- `POST /sandbox` — create a sandbox
- `POST /sandbox/{id}/exec` — run a command
- `POST /sandbox/{id}/write` — write a file
- `GET  /sandbox/{id}/read` — read a file
- `POST /sandbox/{id}/commit` — commit/push (requires `deploy-provision` or higher)
- `DELETE /sandbox/{id}` — destroy the sandbox

Every action is logged to `huvia-core.agent_traces`.

## Status

Scaffold only. Full implementation is a follow-up project.
