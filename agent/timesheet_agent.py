"""
timesheet_agent.py — Kantata Auto-Timesheet Agent

Orchestrates the full weekly timesheet automation:
  1. Fetch calendar events + Teams meetings via calendar_connector MCP
  2. Fetch open Kantata projects via kantata_connector MCP
  3. Call Claude Opus 4.8 to map events → draft timesheet entries
  4. Send draft digest to consultant via Teams webhook (or print to stdout in dry-run)
  5. Wait for approval reply (Teams bot / polling)
  6. Parse the reply with Claude and apply edits
  7. Submit approved entries via kantata_connector MCP

Usage:
    python agent/timesheet_agent.py               # full run
    python agent/timesheet_agent.py --dry-run     # draft only, no writes or messages
    python agent/timesheet_agent.py --list-projects
    python agent/timesheet_agent.py --start 2026-06-23 --end 2026-06-30
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import anthropic
import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(".env.local")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("timesheet_agent")

MODEL = "claude-opus-4-8"
PENDING_STATE_FILE = Path("data/pending_timesheets.json")
MCP_CALENDAR = Path("mcp/calendar_connector.py")
MCP_KANTATA = Path("mcp/kantata_connector.py")


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

MAP_EVENTS_SYSTEM = """\
You are a timesheet assistant for a private equity operations consultancy.
Your job is to map calendar events to Kantata (formerly Mavenlink) project and task IDs.

You will receive:
1. A list of calendar events (title, start, end, duration_minutes, attendees)
2. A list of open Kantata projects (project_id, title, client_name)
3. A project mapping dictionary (event title patterns → known project/task IDs)

Return a JSON array of timesheet entries. Each entry must have:
  - row: integer (1-based index)
  - date: ISO 8601 YYYY-MM-DD
  - hours: float rounded to nearest 0.25
  - project_id: string
  - task_id: string
  - project_name: string (human-readable)
  - task_name: string (human-readable)
  - description: string (1 sentence describing the work)
  - confidence: "high" | "medium" | "low"
  - source_events: list of event titles that contributed to this entry

Rules:
- Merge back-to-back events for the same project into a single entry per day
- Skip events shorter than {min_minutes} minutes
- Round durations to the nearest 15 minutes
- If you cannot confidently map an event, use the fallback project/task and set confidence "low"
- Do NOT fabricate project IDs — only use IDs from the provided project list or mapping

Return only the JSON array. No prose, no markdown fences.
"""

PARSE_APPROVAL_SYSTEM = """\
You are parsing a consultant's reply to a draft timesheet digest.

The consultant received a numbered list of timesheet rows and replied in natural language.
Extract their intent and return a JSON object with:

  {
    "action": "approve_all" | "approve_partial" | "edit" | "hold",
    "approved_rows": [list of row numbers to approve, or "all"],
    "edits": [
      {
        "row": integer,
        "field": "hours" | "project_id" | "task_id" | "description",
        "new_value": string or number
      }
    ],
    "held_rows": [list of row numbers to hold],
    "raw_reply": "the original reply text"
  }

If the reply is "approve" or equivalent with no qualifiers, set action="approve_all".
If the reply mentions specific rows, populate approved_rows and/or edits accordingly.
If the reply is "hold" or equivalent, set action="hold".
If the reply is ambiguous, set action="hold" and include a note in raw_reply.

Return only the JSON object. No prose.
"""


# ---------------------------------------------------------------------------
# MCP client setup
# ---------------------------------------------------------------------------

def build_mcp_params() -> list[anthropic.types.beta.BetaRequestMCPServerToolDefinitionParam]:
    """Return MCP server parameters for both connectors."""
    from anthropic.types.beta import BetaRequestMCPServerURLDefinitionParam  # noqa: F401

    python = sys.executable
    return [
        {
            "type": "url",
            "name": "calendar_connector",
            "url": f"stdio://{python} {MCP_CALENDAR}",
        },
        {
            "type": "url",
            "name": "kantata_connector",
            "url": f"stdio://{python} {MCP_KANTATA}",
        },
    ]


def get_mcp_client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------------------
# Tool execution helpers (manual agentic loop)
# ---------------------------------------------------------------------------

def run_tool_loop(
    client: Anthropic,
    messages: list[dict],
    tools: list[dict],
    system: str,
    *,
    dry_run: bool = False,
) -> tuple[str, list[dict]]:
    """Run the Claude tool-use agentic loop until stop_reason == 'end_turn'.

    Returns (final_text, updated_messages).
    Uses streaming + get_final_message() to handle large outputs.
    """
    while True:
        with client.messages.stream(
            model=MODEL,
            max_tokens=8192,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
        ) as stream:
            response = stream.get_final_message()

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks), messages

        if response.stop_reason != "tool_use":
            log.warning("Unexpected stop_reason: %s", response.stop_reason)
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            log.info("Calling tool: %s(%s)", block.name, json.dumps(block.input)[:120])
            if dry_run and block.name == "create_time_entry":
                result = {"status": "dry_run_skipped"}
            else:
                result = _dispatch_tool(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return "", messages


def _dispatch_tool(name: str, args: dict) -> Any:
    """
    Placeholder dispatcher — in production these calls go through the MCP client.
    Replace with actual MCP tool invocation once the MCP servers are wired up.
    """
    log.warning("_dispatch_tool is a stub for tool '%s'. Wire up MCP servers.", name)
    return {"error": f"Tool '{name}' not yet wired to MCP server."}


# ---------------------------------------------------------------------------
# Core agent steps
# ---------------------------------------------------------------------------

def load_project_mapping() -> dict:
    mapping_path = Path("config/project_mapping.yaml")
    if not mapping_path.exists():
        return {"mappings": [], "defaults": {}}
    with open(mapping_path) as f:
        return yaml.safe_load(f) or {}


def build_draft_entries(
    client: Anthropic,
    start_date: str,
    end_date: str,
    mapping: dict,
    *,
    dry_run: bool,
) -> list[dict]:
    """Step 1–3: fetch calendar, fetch projects, ask Claude to map → draft entries."""
    log.info("Fetching calendar events for %s – %s", start_date, end_date)

    min_minutes = mapping.get("defaults", {}).get("min_duration_minutes", 15)
    system = MAP_EVENTS_SYSTEM.format(min_minutes=min_minutes)

    tools = [
        {
            "name": "get_calendar_events",
            "description": "Fetch Outlook calendar events for a date range.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
        },
        {
            "name": "get_teams_meetings",
            "description": "Fetch Teams online meetings for a date range.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
        },
        {
            "name": "list_projects",
            "description": "List all open Kantata projects.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_tasks",
            "description": "List tasks for a Kantata project.",
            "input_schema": {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        },
    ]

    messages = [
        {
            "role": "user",
            "content": (
                f"Please draft timesheet entries for the period {start_date} to {end_date}. "
                f"Use the following project mapping as your priority reference:\n"
                f"{json.dumps(mapping, indent=2)}\n\n"
                f"Fetch the calendar events, fetch the open Kantata projects, then "
                f"return the draft timesheet JSON array."
            ),
        }
    ]

    raw, _ = run_tool_loop(client, messages, tools, system, dry_run=dry_run)

    try:
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise ValueError("Expected a JSON array")
        return entries
    except (json.JSONDecodeError, ValueError) as e:
        log.error("Claude returned non-JSON draft: %s\n%s", e, raw[:500])
        return []


def format_digest(entries: list[dict], start_date: str, end_date: str) -> str:
    """Format the draft entries as a Teams-friendly text message."""
    lines = [
        f"**Weekly Timesheet Draft — {start_date} to {end_date}**",
        "",
        "| Row | Date | Hours | Project | Task | Confidence |",
        "|-----|------|-------|---------|------|------------|",
    ]
    for e in entries:
        conf_emoji = {"high": "✓", "medium": "~", "low": "?"}.get(
            e.get("confidence", "low"), "?"
        )
        lines.append(
            f"| {e['row']} | {e['date']} | {e['hours']}h "
            f"| {e.get('project_name', e['project_id'])} "
            f"| {e.get('task_name', e['task_id'])} "
            f"| {conf_emoji} {e.get('confidence', '')} |"
        )
    lines += [
        "",
        "Reply with:",
        "  • **approve** — submit all rows",
        "  • **approve rows 1,3** — submit only those rows",
        "  • **edit row 2: 1.5h Portfolio Review** — update and submit",
        "  • **hold** — save for next week",
    ]
    return "\n".join(lines)


def send_teams_digest(digest: str, webhook_url: str) -> bool:
    """Post digest to a Teams incoming webhook.

    Returns True on success.
    """
    import requests  # lazy import

    payload = {"text": digest}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Teams digest sent successfully.")
        return True
    except Exception as exc:
        log.error("Failed to send Teams digest: %s", exc)
        return False


def parse_approval_reply(client: Anthropic, reply_text: str, entries: list[dict]) -> dict:
    """Step 6: ask Claude to parse the consultant's approval reply."""
    messages = [
        {
            "role": "user",
            "content": (
                f"Here is the draft timesheet that was sent:\n"
                f"{json.dumps(entries, indent=2)}\n\n"
                f"Here is the consultant's reply:\n{reply_text}\n\n"
                f"Parse the reply and return the JSON approval object."
            ),
        }
    ]

    with client.messages.stream(
        model=MODEL,
        max_tokens=2048,
        system=PARSE_APPROVAL_SYSTEM,
        messages=messages,
        thinking={"type": "adaptive"},
    ) as stream:
        response = stream.get_final_message()

    text = next(
        (b.text for b in response.content if b.type == "text"), "{}"
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.error("Failed to parse approval response: %s", text[:300])
        return {"action": "hold", "raw_reply": reply_text}


def submit_entries(
    client: Anthropic,
    entries: list[dict],
    approval: dict,
    *,
    dry_run: bool,
) -> list[str]:
    """Step 7: submit approved entries to Kantata."""
    action = approval.get("action", "hold")
    if action == "hold":
        log.info("Action=hold — no entries submitted.")
        return []

    approved_rows = approval.get("approved_rows", "all")
    edits = {e["row"]: e for e in approval.get("edits", [])}

    to_submit = []
    for entry in entries:
        row = entry["row"]
        if approved_rows != "all" and row not in approved_rows:
            continue
        if row in edits:
            edit = edits[row]
            entry = {**entry, edit["field"]: edit["new_value"]}
        to_submit.append(entry)

    tools = [
        {
            "name": "create_time_entry",
            "description": "Submit a single time entry to Kantata.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "date": {"type": "string"},
                    "hours": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["project_id", "task_id", "date", "hours"],
            },
        },
        {
            "name": "list_time_entries",
            "description": "Check for existing time entries (deduplication).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    ]

    messages = [
        {
            "role": "user",
            "content": (
                f"Please submit the following approved timesheet entries to Kantata. "
                f"First check for existing entries to avoid duplicates, then submit each one.\n\n"
                f"{json.dumps(to_submit, indent=2)}"
            ),
        }
    ]

    system = (
        "You are submitting approved timesheet entries to Kantata. "
        "First call list_time_entries to check for duplicates, then call create_time_entry "
        "for each entry that is not already present. "
        "Return a summary of what was submitted."
    )

    result_text, _ = run_tool_loop(client, messages, tools, system, dry_run=dry_run)
    log.info("Submission result: %s", result_text[:300])
    return [e["row"] for e in to_submit]


# ---------------------------------------------------------------------------
# State persistence (simple JSON file)
# ---------------------------------------------------------------------------

def save_pending(entries: list[dict], start_date: str, end_date: str) -> None:
    PENDING_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "week": f"{start_date}:{end_date}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    PENDING_STATE_FILE.write_text(json.dumps(state, indent=2))


def load_pending() -> dict | None:
    if not PENDING_STATE_FILE.exists():
        return None
    try:
        return json.loads(PENDING_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_pending() -> None:
    if PENDING_STATE_FILE.exists():
        PENDING_STATE_FILE.unlink()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Kantata Auto-Timesheet Agent")
    parser.add_argument("--dry-run", action="store_true", help="No writes, no messages")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--list-projects", action="store_true")
    parser.add_argument("--list-tasks", action="store_true")
    parser.add_argument("--project-id", default=None)
    parser.add_argument(
        "--approve",
        metavar="REPLY",
        default=None,
        help="Provide an approval reply string (for testing)",
    )
    args = parser.parse_args()

    client = get_mcp_client()
    mapping = load_project_mapping()

    # --list-projects shortcut
    if args.list_projects:
        result = _dispatch_tool("list_projects", {})
        print(json.dumps(result, indent=2))
        return

    if args.list_tasks:
        if not args.project_id:
            print("--list-tasks requires --project-id")
            sys.exit(1)
        result = _dispatch_tool("list_tasks", {"project_id": args.project_id})
        print(json.dumps(result, indent=2))
        return

    # Date range defaults to last 7 days
    today = date.today()
    start_date = args.start or (today - timedelta(days=7)).isoformat()
    end_date = args.end or today.isoformat()

    dry_run = args.dry_run or os.getenv("DRY_RUN", "false").lower() == "true"
    if dry_run:
        log.info("DRY RUN mode — no Kantata writes, no Teams messages")

    # Check for pending draft from a previous run
    pending = load_pending()
    if pending and pending.get("week") == f"{start_date}:{end_date}":
        log.info("Resuming pending draft from previous run.")
        entries = pending["entries"]
    else:
        entries = build_draft_entries(
            client, start_date, end_date, mapping, dry_run=dry_run
        )
        if not entries:
            log.error("No draft entries generated. Check MCP server stubs.")
            sys.exit(1)
        save_pending(entries, start_date, end_date)

    digest = format_digest(entries, start_date, end_date)

    if dry_run:
        print("\n" + "=" * 60)
        print("DRAFT TIMESHEET (dry run — not sent to Teams)")
        print("=" * 60)
        print(digest)
        print("=" * 60)
        return

    # Send digest
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    if webhook_url:
        send_teams_digest(digest, webhook_url)
    else:
        log.info("TEAMS_WEBHOOK_URL not set — printing digest to stdout")
        print(digest)

    # Parse approval (in production, poll for Teams reply or wait for webhook callback)
    if args.approve:
        reply_text = args.approve
    else:
        print("\nPaste the consultant's approval reply and press Enter twice:")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        reply_text = "\n".join(lines)

    approval = parse_approval_reply(client, reply_text, entries)
    log.info("Parsed approval: %s", json.dumps(approval))

    submitted_rows = submit_entries(client, entries, approval, dry_run=dry_run)

    if submitted_rows:
        log.info("Submitted %d entries to Kantata: rows %s", len(submitted_rows), submitted_rows)
        clear_pending()
    else:
        log.info("No entries submitted (hold or no approved rows).")


if __name__ == "__main__":
    main()
