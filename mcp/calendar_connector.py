"""
calendar_connector.py — MCP server wrapping Microsoft Graph calendar and Teams meeting APIs.

Exposes two tools to Claude:
  - get_calendar_events(start_date, end_date)
  - get_teams_meetings(start_date, end_date)

Authentication: OAuth2 delegated flow via azure-identity DeviceCodeCredential.
On first run, prints a device code URL to stdout for the user to authenticate.
The credential handles token refresh automatically for the duration of the process.
"""

import json
import logging
import os
from datetime import datetime, timezone

import mcp.server.stdio
import mcp.types as types
from dotenv import load_dotenv
from mcp.server import Server

load_dotenv(".env.local")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calendar_connector")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_credential = None


# ---------------------------------------------------------------------------
# Token helper
# ---------------------------------------------------------------------------

def get_access_token() -> str:
    """Return a valid Microsoft Graph access token via DeviceCodeCredential.

    On first call, prints a device code URL to the console for the user to
    authenticate in a browser. Subsequent calls reuse the cached credential.
    """
    global _credential
    from azure.identity import DeviceCodeCredential

    if _credential is None:
        _credential = DeviceCodeCredential(
            client_id=os.environ["GRAPH_CLIENT_ID"],
            tenant_id=os.environ["GRAPH_TENANT_ID"],
        )
    token = _credential.get_token("https://graph.microsoft.com/.default")
    return token.token


def graph_get(path: str, token: str, params: dict | None = None) -> dict:
    """Make a GET request to Microsoft Graph and return the parsed JSON."""
    import requests  # lazy import to keep startup fast

    resp = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

server = Server("calendar_connector")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_calendar_events",
            description=(
                "Fetch the authenticated user's Outlook calendar events between "
                "start_date and end_date (ISO 8601 date strings, e.g. '2026-06-23'). "
                "Returns a list of events with title, start, end, duration_minutes, "
                "attendees, and online_meeting flag."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in ISO 8601 format (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in ISO 8601 format (YYYY-MM-DD)",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        ),
        types.Tool(
            name="get_teams_meetings",
            description=(
                "Fetch Microsoft Teams online meetings the user organised or attended "
                "between start_date and end_date. Returns subject, start, end, "
                "duration_minutes, and attendees. Falls back to filtering calendar "
                "events with isOnlineMeeting=true."
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    token = get_access_token()
    start = arguments["start_date"]
    end = arguments["end_date"]

    if name == "get_calendar_events":
        events = _fetch_calendar_events(token, start, end)
        return [types.TextContent(type="text", text=json.dumps(events))]

    if name == "get_teams_meetings":
        meetings = _fetch_teams_meetings(token, start, end)
        return [types.TextContent(type="text", text=json.dumps(meetings))]

    raise ValueError(f"Unknown tool: {name}")


def _fetch_calendar_events(token: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch calendar events from /me/calendarView with pagination."""
    start_dt = f"{start_date}T00:00:00Z"
    end_dt = f"{end_date}T23:59:59Z"

    events = []
    url = "/me/calendarView"
    params = {
        "startDateTime": start_dt,
        "endDateTime": end_dt,
        "$select": "subject,start,end,attendees,isOnlineMeeting,onlineMeetingUrl",
        "$top": 100,
    }

    while url:
        data = graph_get(url, token, params)
        for ev in data.get("value", []):
            start = datetime.fromisoformat(ev["start"]["dateTime"].rstrip("Z")).replace(
                tzinfo=timezone.utc
            )
            end = datetime.fromisoformat(ev["end"]["dateTime"].rstrip("Z")).replace(
                tzinfo=timezone.utc
            )
            duration_minutes = int((end - start).total_seconds() / 60)
            events.append(
                {
                    "title": ev.get("subject", "(no title)"),
                    "start": ev["start"]["dateTime"],
                    "end": ev["end"]["dateTime"],
                    "duration_minutes": duration_minutes,
                    "attendees": [
                        a["emailAddress"]["address"]
                        for a in ev.get("attendees", [])
                        if a.get("emailAddress")
                    ],
                    "is_online_meeting": ev.get("isOnlineMeeting", False),
                }
            )
        # Follow pagination link; clear params so nextLink URL is used as-is
        next_link = data.get("@odata.nextLink")
        if next_link:
            # nextLink is a full URL; strip the base so graph_get can prepend it
            url = next_link.replace(GRAPH_BASE, "")
            params = {}
        else:
            url = None

    return events


def _fetch_teams_meetings(token: str, start_date: str, end_date: str) -> list[dict]:
    """Return Teams meetings by filtering calendar events with isOnlineMeeting=True.

    The /me/onlineMeetings endpoint only covers meetings the user organised,
    so we use the calendar view (which includes all attended meetings) and
    filter on the isOnlineMeeting flag instead.
    """
    all_events = _fetch_calendar_events(token, start_date, end_date)
    return [ev for ev in all_events if ev.get("is_online_meeting")]


if __name__ == "__main__":
    import asyncio

    asyncio.run(mcp.server.stdio.stdio_server(server))
