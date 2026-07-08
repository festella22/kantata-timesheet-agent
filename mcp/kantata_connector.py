"""
kantata_connector.py — MCP server wrapping the Kantata REST API v1.

Exposes four tools to Claude:
  - list_projects()
  - list_tasks(project_id)
  - list_time_entries(start_date, end_date)
  - create_time_entry(project_id, task_id, date, hours, notes)

Authentication: OAuth2 client credentials flow.
  POST https://app.mavenlink.com/oauth/token
  with client_id + client_secret → access token.

Kantata API docs: https://developer.kantata.com/
"""

import json
import logging
import os

import mcp.server.stdio
import mcp.types as types
from dotenv import load_dotenv
from mcp.server import Server

load_dotenv(".env.local")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kantata_connector")

# TODO: BASE_URL — US: https://app.mavenlink.com  EU: https://app.eu.mavenlink.com
KANTATA_BASE = os.getenv("KANTATA_BASE_URL", "https://app.mavenlink.com")

_token_cache: dict = {}


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def get_access_token() -> str:
    """Return a valid Kantata access token using client credentials flow."""
    import requests
    import time

    if _token_cache.get("expires_at", 0) > time.time() + 60:
        return _token_cache["access_token"]

    resp = requests.post(
        f"{KANTATA_BASE}/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["KANTATA_CLIENT_ID"],
            "client_secret": os.environ["KANTATA_CLIENT_SECRET"],
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return data["access_token"]


def kantata_get(path: str, params: dict | None = None) -> dict:
    """GET from Kantata API, returning parsed JSON."""
    import requests  # lazy import

    token = get_access_token()
    resp = requests.get(
        f"{KANTATA_BASE}/api/v1{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        params=params or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def kantata_post(path: str, payload: dict) -> dict:
    """POST to Kantata API, returning parsed JSON."""
    import requests  # lazy import

    token = get_access_token()
    resp = requests.post(
        f"{KANTATA_BASE}/api/v1{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

server = Server("kantata_connector")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_projects",
            description=(
                "Return all open Kantata projects the authenticated user can log "
                "time to. Each entry includes project_id, title, and client_name."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="list_tasks",
            description="Return tasks for a given Kantata project_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Kantata project ID",
                    }
                },
                "required": ["project_id"],
            },
        ),
        types.Tool(
            name="list_time_entries",
            description=(
                "Fetch existing time entries for the current user between "
                "start_date and end_date (ISO 8601 YYYY-MM-DD). Used for "
                "deduplication before submitting new entries."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
        ),
        types.Tool(
            name="create_time_entry",
            description=(
                "Submit a single approved time entry to Kantata. "
                "hours is a float (e.g. 1.5). date is ISO 8601 YYYY-MM-DD. "
                "Returns the created entry ID on success."
            ),
            inputSchema={
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
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "list_projects":
        result = _list_projects()
    elif name == "list_tasks":
        result = _list_tasks(arguments["project_id"])
    elif name == "list_time_entries":
        result = _list_time_entries(arguments["start_date"], arguments["end_date"])
    elif name == "create_time_entry":
        result = _create_time_entry(
            project_id=arguments["project_id"],
            task_id=arguments["task_id"],
            date=arguments["date"],
            hours=float(arguments["hours"]),
            notes=arguments.get("notes", ""),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [types.TextContent(type="text", text=json.dumps(result))]


def _list_projects() -> list[dict]:
    """List open projects.

    Kantata paginates via page[number] / page[size].
    Loops until all pages are fetched.
    """
    projects = []
    page = 1
    while True:
        data = kantata_get(
            "/workspaces",
            params={"include": "primary_counterpart", "page": page, "per_page": 200},
        )
        for ws in data.get("workspaces", {}).values():
            projects.append(
                {
                    "project_id": str(ws["id"]),
                    "title": ws.get("title", ""),
                    "client_name": ws.get("primary_counterpart", {}).get("name", ""),
                    "status": ws.get("status", ""),
                }
            )
        meta = data.get("meta", {})
        if len(projects) >= meta.get("count", len(projects)):
            break
        page += 1
    return projects


def _list_tasks(project_id: str) -> list[dict]:
    """List tasks (stories) for a project."""
    data = kantata_get("/stories", params={"workspace_id": project_id, "type": "task"})
    tasks = []
    for story in data.get("stories", {}).values():
        tasks.append(
            {
                "task_id": str(story["id"]),
                "title": story.get("title", ""),
                "project_id": project_id,
            }
        )
    return tasks


def _list_time_entries(start_date: str, end_date: str) -> list[dict]:
    """Fetch existing time entries for deduplication."""
    data = kantata_get(
        "/time_entries",
        params={"date_range": f"{start_date}:{end_date}"},
    )
    entries = []
    for te in data.get("time_entries", {}).values():
        entries.append(
            {
                "entry_id": str(te["id"]),
                "project_id": str(te.get("workspace_id", "")),
                "task_id": str(te.get("story_id", "")),
                "date": te.get("date_performed", ""),
                "minutes": te.get("time_in_minutes", 0),
                "notes": te.get("notes", ""),
            }
        )
    return entries


def _create_time_entry(
    project_id: str, task_id: str, date: str, hours: float, notes: str
) -> dict:
    """Submit a time entry to Kantata.

    Kantata stores time in minutes, not hours.
    """
    minutes = round(hours * 60)
    payload = {
        "time_entry": {
            "workspace_id": project_id,
            "story_id": task_id,
            "date_performed": date,
            "time_in_minutes": minutes,
            "notes": notes,
        }
    }
    result = kantata_post("/time_entries", payload)
    created = list(result.get("time_entries", {}).values())
    if not created:
        return {"error": "No time entry returned from Kantata"}
    return {"entry_id": str(created[0]["id"]), "status": "created"}


if __name__ == "__main__":
    import asyncio

    asyncio.run(mcp.server.stdio.stdio_server(server))
