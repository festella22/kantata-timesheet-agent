# Kantata Auto-Timesheet Agent

An AI agent that automatically drafts Kantata (formerly Mavenlink) timesheet entries from a consultant's Outlook calendar and Microsoft Teams meeting history, then presents a weekly digest for human review and one-click approval before submitting to the Kantata API.

Built on [Claude Opus 4.8](https://docs.anthropic.com/en/docs/about-claude/models), Microsoft Graph API, and the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Human-in-the-Loop Flow](#human-in-the-loop-flow)
4. [Repository Structure](#repository-structure)
5. [Prerequisites](#prerequisites)
6. [Setup & Configuration](#setup--configuration)
7. [Project Mapping Config](#project-mapping-config)
8. [Running the Agent](#running-the-agent)
9. [MCP Servers](#mcp-servers)
10. [API Credentials](#api-credentials)
11. [Contributing / Picking Up This Project](#contributing--picking-up-this-project)

---

## Overview

Consultants at PE-backed portfolio companies spend significant time manually entering billable hours into Kantata every week. This agent eliminates that friction by:

- **Ingesting** Outlook calendar events and Teams meeting records for the past 7 days via Microsoft Graph API
- **Mapping** event titles, attendees, and durations to the correct Kantata project and task using Claude (with a configurable YAML mapping file as a fallback/seed)
- **Generating** a draft timesheet with hours, descriptions, and confidence scores
- **Delivering** a weekly digest to the consultant via Teams bot DM (or email fallback)
- **Parsing** the consultant's natural-language approval reply ("approve", "edit row 3: 2h – Portfolio Review", "hold")
- **Submitting** approved entries directly to the Kantata REST API

### What this is NOT

- Not a fully autonomous system — a human approves every submission
- Not a replacement for judgment — Claude drafts, the consultant decides
- Not connected to billing or finance systems directly

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Scheduler (cron)                    │
│              runs every Monday morning 8 AM              │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│               timesheet_agent.py (main loop)             │
│                                                          │
│  1. Call calendar_connector MCP → fetch last 7d events   │
│  2. Call kantata_connector MCP  → fetch open projects    │
│  3. Call Claude Opus 4.8        → map events → tasks     │
│  4. Generate draft JSON         → timesheet entries      │
│  5. Send digest via Teams/email → human review           │
│  6. Wait for reply (24h window) → parse approval         │
│  7. Call kantata_connector MCP  → submit approved rows   │
└──────────────┬─────────────────────────┬────────────────┘
               │                         │
               ▼                         ▼
 ┌─────────────────────┐   ┌──────────────────────────┐
 │ calendar_connector  │   │   kantata_connector       │
 │ (MCP server)        │   │   (MCP server)            │
 │                     │   │                           │
 │ Microsoft Graph API │   │ Kantata REST API v1        │
 │ - Outlook Calendar  │   │ - GET /projects            │
 │ - Teams meetings    │   │ - GET /tasks               │
 └─────────────────────┘   │ - POST /time_entries       │
                           └──────────────────────────┘
```

### Component Roles

| Component | File | Responsibility |
|---|---|---|
| Main agent loop | `agent/timesheet_agent.py` | Orchestrates Claude tool calls; handles HITL state machine |
| Calendar MCP server | `mcp/calendar_connector.py` | Wraps Microsoft Graph `/me/calendarView` and `/me/onlineMeetings` |
| Kantata MCP server | `mcp/kantata_connector.py` | Wraps Kantata REST `/api/v1/projects`, `/tasks`, `/time_entries` |
| Project mapping | `config/project_mapping.yaml` | Seed dictionary: event title patterns → Kantata project/task IDs |
| Claude slash command | `.claude/commands/timesheet.md` | `/timesheet` skill for manual one-off runs inside Claude Code |

### Claude API Usage

- **Model**: `claude-opus-4-8`
- **Thinking**: `{"type": "adaptive"}` — lets Claude self-budget reasoning depth
- **Streaming**: enabled for all calls (avoids timeout on large calendar windows)
- **Tool use**: manual agentic loop — agent code controls when to call each MCP tool and when to stop
- **Two Claude calls per run**:
  1. `map_events` — given raw calendar events + open Kantata projects, return structured draft entries
  2. `parse_approval` — given the consultant's freeform reply, return structured approval/edit/hold actions

---

## Human-in-the-Loop Flow

```
Monday 8 AM
    │
    ▼
Agent drafts timesheet
    │
    ▼
Teams DM sent to consultant:
  ┌──────────────────────────────────────────────────────┐
  │ Weekly Timesheet Draft – Week of Jun 30              │
  │                                                      │
  │  Row  Date    Hours  Project           Task          │
  │  1.   Mon     2.0h   Acme Portfolio    Ops Review    │
  │  2.   Mon     1.5h   Internal          BD Call       │
  │  3.   Tue     3.0h   Brightwood M&A    Due Diligence │
  │  ...                                                 │
  │                                                      │
  │ Reply: "approve" / "edit row 3: 2h DD prep" / "hold" │
  └──────────────────────────────────────────────────────┘
    │
    ▼ consultant replies (24h window)
    │
    ├─ "approve"           → submit all rows to Kantata
    ├─ "approve rows 1,2"  → submit only those rows
    ├─ "edit row 3: 2h DD prep" → update row 3, then submit
    ├─ "hold"              → save draft, send reminder next Monday
    └─ no reply (timeout)  → send reminder, hold for next week
```

Approval state is stored in `data/pending_timesheets.json` (gitignored). Each run is idempotent — re-running on the same week returns the pending draft rather than re-fetching.

---

## Repository Structure

```
kantata-timesheet-agent/
├── README.md                        ← this file
├── CLAUDE.md                        ← project context for Claude Code
├── .env.example                     ← credential template (copy → .env.local)
├── requirements.txt
├── .gitignore
│
├── .claude/
│   └── commands/
│       └── timesheet.md             ← /timesheet slash command
│
├── mcp/
│   ├── calendar_connector.py        ← Microsoft Graph MCP server (stub → implement)
│   └── kantata_connector.py         ← Kantata REST API MCP server (stub → implement)
│
├── agent/
│   └── timesheet_agent.py           ← main agent orchestration
│
├── config/
│   └── project_mapping.yaml         ← event title → Kantata project/task seed map
│
└── scripts/
    └── export_skill.py              ← package as .skill file for Claude Code
```

---

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- A registered [Azure AD app](https://portal.azure.com/) with Microsoft Graph delegated permissions:
  - `Calendars.Read`
  - `OnlineMeetings.Read`
  - `User.Read`
- Kantata (Mavenlink) account with API access — obtain OAuth credentials from your Kantata workspace admin
- (Optional) Microsoft Teams bot registration for digest delivery

---

## Setup & Configuration

```bash
# 1. Clone and enter the repo
git clone https://github.com/festella22/kantata-timesheet-agent.git
cd kantata-timesheet-agent

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp .env.example .env.local
# Edit .env.local — fill in all six required values (see API Credentials section)

# 5. Seed the project mapping (optional but recommended)
# Edit config/project_mapping.yaml with your real Kantata project and task IDs
# (Run python agent/timesheet_agent.py --list-projects to print all open projects)

# 6. Run a dry run (no Kantata submission, prints draft to stdout)
python agent/timesheet_agent.py --dry-run

# 7. Schedule weekly runs (example: cron every Monday 8 AM)
# crontab -e
# 0 8 * * 1 /path/to/.venv/bin/python /path/to/agent/timesheet_agent.py
```

---

## Project Mapping Config

`config/project_mapping.yaml` is the seed dictionary Claude uses when mapping calendar events to Kantata projects and tasks. Claude will still attempt a fuzzy match for events not covered here, but explicit entries improve accuracy and reduce API costs.

### Format

```yaml
# config/project_mapping.yaml
# Maps event title patterns (regex or exact string) to Kantata IDs.
# Claude uses this as a priority reference before attempting its own inference.

mappings:
  - pattern: "Brightwood.*Due Diligence"   # regex matched against event title
    project_id: "123456"                    # Kantata project ID (string)
    task_id: "789012"                       # Kantata task ID (string)
    description_template: "DD session – {event_title}"  # optional; {event_title} is interpolated

  - pattern: "Portfolio Review"
    project_id: "111222"
    task_id: "333444"

  - pattern: "Internal"                    # catch-all for internal meetings
    project_id: "000001"
    task_id: "000002"

defaults:
  fallback_project_id: "000001"           # used when Claude cannot map an event
  fallback_task_id: "000002"
  min_duration_minutes: 15                # events shorter than this are skipped
  round_to_minutes: 15                    # round durations to nearest N minutes
```

### Finding Your Kantata IDs

```bash
# List all open projects and their IDs
python agent/timesheet_agent.py --list-projects

# List tasks for a specific project
python agent/timesheet_agent.py --list-tasks --project-id 123456
```

---

## Running the Agent

### Manual one-off run (CLI)

```bash
# Dry run — print draft to stdout, no Teams message, no Kantata submission
python agent/timesheet_agent.py --dry-run

# Full run — sends Teams DM, waits for approval
python agent/timesheet_agent.py

# Override the date range (default: last 7 days)
python agent/timesheet_agent.py --start 2026-06-23 --end 2026-06-30

# List open projects (useful for populating project_mapping.yaml)
python agent/timesheet_agent.py --list-projects
```

### Via Claude Code slash command

Inside a Claude Code session in this repo:

```
/timesheet
```

This runs the agent via the `.claude/commands/timesheet.md` skill, which supports conversational overrides ("run for last two weeks", "hold the Brightwood row").

---

## MCP Servers

Both MCP servers follow the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) pattern and are registered in the agent via `anthropic[mcp]`.

### calendar_connector.py

Wraps Microsoft Graph API. Tools exposed to Claude:

| Tool | Description |
|---|---|
| `get_calendar_events(start_date, end_date)` | Returns calendar events in the given date range |
| `get_teams_meetings(start_date, end_date)` | Returns Teams online meetings (join URL, attendees, duration) |

**Implementation status**: Stub — OAuth2 flow and Graph API calls are scaffolded. You need to fill in the token refresh logic and the `/me/calendarView` pagination.

### kantata_connector.py

Wraps Kantata REST API v1. Tools exposed to Claude:

| Tool | Description |
|---|---|
| `list_projects()` | Returns all open projects the authenticated user can log time to |
| `list_tasks(project_id)` | Returns tasks for a project |
| `create_time_entry(project_id, task_id, date, hours, notes)` | Submits a single time entry |
| `list_time_entries(start_date, end_date)` | Fetches existing entries (for deduplication) |

**Implementation status**: Stub — authentication and endpoint URLs scaffolded. You need to fill in the OAuth token exchange and handle Kantata's paginated responses.

---

## API Credentials

Copy `.env.example` to `.env.local` and populate all values. **Never commit `.env.local`** — it is in `.gitignore`.

| Variable | Source |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) |
| `KANTATA_CLIENT_ID` | Kantata workspace admin → API credentials |
| `KANTATA_CLIENT_SECRET` | Kantata workspace admin → API credentials |
| `KANTATA_WORKSPACE_ID` | Your Kantata workspace subdomain (e.g. `pipartners`) |
| `GRAPH_CLIENT_ID` | Azure Portal → App registrations → your app → Application (client) ID |
| `GRAPH_CLIENT_SECRET` | Azure Portal → App registrations → your app → Certificates & secrets |
| `GRAPH_TENANT_ID` | Azure Portal → App registrations → your app → Directory (tenant) ID |
| `TEAMS_WEBHOOK_URL` | (Optional) Teams incoming webhook or bot endpoint for digest delivery |

---

## Contributing / Picking Up This Project

This repo is a scaffold — the core logic is in place, but the MCP server implementations and the Teams notification delivery need to be built out. Here is the suggested order of work for a developer picking this up:

### Phase 1 — Wire up the MCP servers (estimated: 1–2 days)

1. **`mcp/calendar_connector.py`** — implement `get_calendar_events()` and `get_teams_meetings()` using the `msgraph-sdk-python` library. Handle OAuth2 delegated flow (interactive browser login on first run, then token cache). See [Microsoft Graph Python SDK](https://github.com/microsoftgraph/msgraph-sdk-python).

2. **`mcp/kantata_connector.py`** — implement `list_projects()`, `list_tasks()`, `create_time_entry()`, and `list_time_entries()` against the [Kantata REST API](https://developer.kantata.com/). Use `requests` with Bearer token auth. Kantata uses standard OAuth2 client credentials flow.

### Phase 2 — Test the mapping logic (estimated: 0.5 days)

3. Run `python agent/timesheet_agent.py --dry-run` and review the draft output. Populate `config/project_mapping.yaml` with real project IDs from `--list-projects`.

4. Adjust the `map_events` Claude prompt in `agent/timesheet_agent.py` if the mapping accuracy is poor for your firm's naming conventions.

### Phase 3 — Teams digest delivery (estimated: 0.5–1 day)

5. Implement `send_teams_digest()` in `agent/timesheet_agent.py`. The simplest approach is an incoming webhook (no bot registration required). For reply parsing, use a Teams bot with an Adaptive Card that has an action button triggering a webhook back to the agent.

6. Alternatively, use the email fallback: `send_email_digest()` via Microsoft Graph `sendMail`.

### Phase 4 — Productionize (estimated: 1 day)

7. Set up a cron job or Azure Functions timer trigger.
8. Add structured logging (the stubs use `logging` already — wire to your observability stack).
9. Add a simple SQLite or Cosmos DB store to replace `data/pending_timesheets.json` if running multi-user.

### Key design decisions to be aware of

- **No streaming to Teams** — Claude's response is buffered before the digest is sent, so the Teams message is always a complete draft.
- **Idempotency** — the agent checks `data/pending_timesheets.json` before re-fetching. Do not delete this file between runs without also clearing the Kantata deduplication check.
- **Claude prompt location** — the `map_events` system prompt is in `agent/timesheet_agent.py`. Keep the project mapping YAML in sync with any prompt changes.
- **MCP server startup** — both MCP servers are started as subprocesses by the agent using `anthropic[mcp]`'s `StdioServerParameters`. They do not need to be running independently.

### Running tests

```bash
pytest tests/ -v
```

Tests use `pytest` with `responses` for HTTP mocking. Add tests for new MCP tool implementations under `tests/mcp/`.

---

## License

MIT — see [LICENSE](LICENSE).

## Maintainer

Built and maintained by [PI Partners](https://pipartners.com). Questions: festella@pipartners.com
