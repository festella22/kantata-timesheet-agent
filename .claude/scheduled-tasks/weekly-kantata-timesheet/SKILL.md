---
name: weekly-kantata-timesheet
description: Every Monday — draft Kantata timesheet from Outlook calendar, email digest for approval, submit on reply
schedule: "0 8 * * 1"
---

You are running the weekly Kantata Auto-Timesheet Agent for festella@pipartners.com at PI Partners.

## Steps

### 1. Read last 7 days of calendar
Use the Microsoft 365 MCP connector to fetch all Outlook calendar events from the past Monday through Sunday. Capture: event title, date, start time, end time, duration in minutes, attendees.

### 2. Map events to Kantata projects
- Fetch the project mapping from: https://raw.githubusercontent.com/festella22/kantata-timesheet-agent/main/config/project_mapping.yaml
- Match event titles (case-insensitive, partial match OK) to the `mappings` entries in that file
- Merge back-to-back events for the same project into one entry per day
- Skip events shorter than `defaults.min_duration_minutes` (default: 15)
- Round durations to the nearest `defaults.round_to_minutes` (default: 15)
- Unmatched events → use `defaults.fallback_project_id` / `defaults.fallback_task_id`, confidence = "low"

### 3. Draft the timesheet table

Format the draft exactly like this:

```
Weekly Timesheet Draft — YYYY-MM-DD to YYYY-MM-DD

Row | Date       | Hours | Project          | Task             | Confidence
----|------------|-------|------------------|------------------|------------
1   | 2026-07-01 | 2.0h  | Acme Portfolio   | Ops Review       | ✓ high
2   | 2026-07-01 | 1.5h  | Internal         | BD Call          | ~ medium
3   | 2026-07-02 | 3.0h  | Brightwood M&A   | Due Diligence    | ✓ high

Total: 6.5h across 3 entries

Reply with:
  • approve              — submit all rows to Kantata
  • approve rows 1,3    — submit only those rows
  • edit row 2: 1.5h Portfolio Review  — update and submit
  • hold                — skip this week, I'll handle manually
```

### 4. Send the digest email
Send to: festella@pipartners.com
Subject: `Weekly Timesheet Draft — [start_date] to [end_date] — Action Required`
Body: the table above.

### 5. Wait for approval reply
Poll the inbox for a reply to this email, up to 24 hours.

| Reply | Action |
|-------|--------|
| "approve" / "approve all" | Submit all rows |
| "approve rows N,M" | Submit only those rows |
| "edit row N: Xh description" | Update that field, then submit |
| "hold" or no reply after 24h | Do not submit — save note for next Monday |

Never submit to Kantata without an explicit approval reply.

### 6. Submit approved rows to Kantata

**Auth:** POST to `{KANTATA_BASE_URL}/oauth/token`
```
grant_type=client_credentials
client_id={KANTATA_CLIENT_ID}
client_secret={KANTATA_CLIENT_SECRET}
```

**Dedup check first:** GET `{KANTATA_BASE_URL}/api/v1/time_entries?date_range={start}:{end}` — skip any row whose project_id + task_id + date already exists.

**Submit each row:** POST to `{KANTATA_BASE_URL}/api/v1/time_entries`
```json
{
  "time_entry": {
    "workspace_id": "{project_id}",
    "story_id": "{task_id}",
    "date_performed": "{YYYY-MM-DD}",
    "time_in_minutes": {hours * 60},
    "notes": "{description}"
  }
}
```

**Send confirmation email** to festella@pipartners.com listing submitted entry IDs.

## Environment variables required
| Variable | Where to get it |
|----------|----------------|
| `KANTATA_CLIENT_ID` | Kantata workspace admin → Settings → API |
| `KANTATA_CLIENT_SECRET` | Same |
| `KANTATA_BASE_URL` | Default: `https://app.mavenlink.com` (EU: `https://app.eu.mavenlink.com`) |

## Edge cases
- **No calendar events found:** Email festella@pipartners.com: "No events found for [week]. If this looks wrong, check that the Microsoft 365 connector is authorised in Claude Code settings."
- **Kantata credentials missing:** Still send the digest email; append: "⚠️ Kantata credentials not set — entries cannot be submitted until KANTATA_CLIENT_ID and KANTATA_CLIENT_SECRET are configured."
- **Kantata API error:** Email the error to festella@pipartners.com and hold the draft for next week.

## Context
- User: festella@pipartners.com — PI Partners, private equity operations consultancy
- Kantata workspace subdomain: pipartners
- This is human-in-the-loop — the draft is always reviewed before submission
- Project/task mapping lives in `config/project_mapping.yaml` in this repo

## To activate this schedule in Claude Code
1. Copy this file to: `~/.claude/scheduled-tasks/weekly-kantata-timesheet/SKILL.md`
2. Open Claude Code — the task will appear in scheduled tasks and run every Monday at 8 AM local time.
3. Ensure the Microsoft 365 connector is authorised (claude.ai connector settings).
4. Set `KANTATA_CLIENT_ID` and `KANTATA_CLIENT_SECRET` in your environment.
