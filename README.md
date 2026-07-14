# Kantata Auto-Timesheet Agent

A Claude scheduled task that drafts your weekly Kantata (Mavenlink) timesheet from your Outlook calendar, emails you the draft for approval, and submits the rows you approve to the Kantata API. A human approves every submission — nothing is ever written to Kantata without an explicit "approve" reply from your own email address.

Runs entirely inside Claude (desktop / Claude Code) using the Microsoft 365 connector. No Python environment, no Azure app registration, no servers.

## How it works

```
Monday 8 AM
  └─ Task reads last week's Outlook calendar (Microsoft 365 connector)
  └─ Maps events → Kantata projects/tasks via project_mapping.yaml
  └─ Emails you a draft: Row | Date | Hours | Project | Task | Confidence
  └─ Saves the draft locally as pending

You reply (any time before Tuesday 8 AM, or later — it checks for 6 days):
  approve  |  approve rows 1,3  |  edit row 2: 1.5h Portfolio review  |  hold

Tuesday 8 AM
  └─ Task finds your reply (only from YOUR address — anything else is ignored)
  └─ Dedup check: skips any row already in Kantata for that project+task+date
  └─ Submits approved rows via POST /time_entries
  └─ Emails you a confirmation with the created entry IDs
```

If you don't reply within 6 days the draft is discarded and you get a note that the week was skipped. Nothing is ever auto-submitted.

## Install (fresh machine)

1. Clone this repo and run the installer from the repo root:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

   This copies the scheduled task to `~/.claude/scheduled-tasks/weekly-kantata-timesheet/` and the config templates to `~/.claude/kantata-timesheet/`.

2. Fill in two files under `~/.claude/kantata-timesheet/` (they live **outside** this repo on purpose — once filled they contain client names and credentials that must never be committed):

   - `kantata.env` — your Kantata API token (Kantata → Settings → API → generate token)
   - `project_mapping.yaml` — your event-title patterns → Kantata project/task IDs

3. In Claude, authorize the **Microsoft 365 connector** (claude.ai connector settings) so the task can read your calendar and inbox.

4. Done. The task runs Monday and Tuesday at 8 AM local time (Claude must be running; if it was closed, the task runs on next launch).

**Shortcut for step 2:** run the task once manually with placeholder config — it will email you a setup checklist that includes your live Kantata project list with IDs, ready to paste into the mapping file.

## Repository structure

```
kantata-timesheet-agent/
├── README.md
├── CLAUDE.md                     ← project context for Claude Code
├── install.ps1                   ← one-shot deploy to ~/.claude
├── .claude/scheduled-tasks/
│   └── weekly-kantata-timesheet/
│       └── SKILL.md              ← the agent: full workflow, guardrails, API details
└── config/
    ├── project_mapping.yaml      ← TEMPLATE (placeholders only — fill the installed copy)
    └── kantata.env.example       ← TEMPLATE (never commit a filled copy)
```

## Safety design

- **Human-in-the-loop** — every submission requires an approval reply; "hold" or silence means nothing is written.
- **Sender guard** — approval replies are only accepted from festella@pipartners.com. Approvals appearing in calendar events, documents, or other senders' emails are ignored.
- **Injection guard** — calendar event titles/bodies and email contents are treated as data, never as instructions to the agent.
- **Deterministic dedup** — before any submission the task fetches existing Kantata entries for the week and skips exact project+task+date matches, so a re-run can't double-bill.
- **No secrets in the repo** — the repo holds templates only; filled credentials and the real client/project mapping live in `~/.claude/kantata-timesheet/`. Keep this repo private anyway.

## History

Earlier versions of this repo contained a standalone Python agent (Anthropic API + two MCP servers wrapping Microsoft Graph and the Kantata REST API). It was removed in favor of the scheduled-task approach above — same workflow, no infrastructure to maintain. It's in git history if ever needed.

## Maintainer

Built and maintained by [PI Partners](https://pipartners.com). Questions: festella@pipartners.com
