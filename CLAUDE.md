# Kantata Auto-Timesheet Agent — Claude Code Context

## What this project does

Automates Kantata (Mavenlink) timesheet entry for PE consultants. Reads Outlook calendar + Teams meetings via Microsoft Graph API, maps events to Kantata projects/tasks using Claude Opus 4.8, generates a draft weekly timesheet, sends it to the consultant for approval, and submits approved entries to Kantata's REST API.

## Architecture overview

- `agent/timesheet_agent.py` — main Claude API agentic loop (Workflow tier: manual tool use loop)
- `mcp/calendar_connector.py` — MCP server wrapping Microsoft Graph calendar/meetings endpoints
- `mcp/kantata_connector.py` — MCP server wrapping Kantata REST API (projects, tasks, time entries)
- `config/project_mapping.yaml` — seed dictionary: event title patterns → Kantata project/task IDs
- `.claude/commands/timesheet.md` — `/timesheet` slash command for manual runs inside Claude Code

## Claude API conventions used here

- Model: `claude-opus-4-8`
- Thinking: `{"type": "adaptive"}` (NOT `budget_tokens` — that's rejected on 4.8)
- Streaming: always on (large calendar windows can produce verbose output)
- Tool use: manual agentic loop, NOT Managed Agents (PI Partners hosts the compute)
- MCP: `anthropic[mcp]` — both connectors run as stdio subprocesses spawned by the agent

## Key files to read before making changes

1. `agent/timesheet_agent.py` — understand the two Claude calls (`map_events`, `parse_approval`) before touching prompt logic
2. `config/project_mapping.yaml` — must stay in sync with the `map_events` system prompt
3. `.env.example` — all required credential names; copy to `.env.local` to run locally

## Credential rules

- ALL credentials live in `.env.local` only — never commit this file
- Required: `ANTHROPIC_API_KEY`, `KANTATA_CLIENT_ID`, `KANTATA_CLIENT_SECRET`, `KANTATA_WORKSPACE_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_TENANT_ID`
- Optional: `TEAMS_WEBHOOK_URL`

## Common tasks

```bash
# Dry run (no Teams message, no Kantata write)
python agent/timesheet_agent.py --dry-run

# List open Kantata projects (to populate project_mapping.yaml)
python agent/timesheet_agent.py --list-projects

# Run tests
pytest tests/ -v
```

## What's not done yet (Phase 1 priority)

- `mcp/calendar_connector.py` — OAuth flow + Graph API calls are stubs
- `mcp/kantata_connector.py` — OAuth + Kantata endpoints are stubs
- Teams bot reply handling — email fallback is the current path
- See README.md "Contributing / Picking Up This Project" for the full build-out plan

## Kantata API notes

- Base URL: `https://api.kantata.com/api/v1/` (EU: `https://api.eu.kantata.com/api/v1/`)
- Auth: OAuth2 client credentials → Bearer token
- Pagination: cursor-based via `page[number]` and `page[size]` query params
- Time entries: `POST /time_entries` with `time_entry[minutes]` (not hours), `time_entry[date]` (ISO 8601), `time_entry[story_id]` (task ID)

## Microsoft Graph API notes

- Calendar events: `GET /me/calendarView?startDateTime=...&endDateTime=...`
- Teams meetings: `GET /me/onlineMeetings` (requires `OnlineMeetings.Read` scope)
- Auth: OAuth2 delegated flow (interactive login first run, then token cache in `.token_cache`)
