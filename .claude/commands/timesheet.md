# /timesheet — Run the Kantata Auto-Timesheet Agent

Run the timesheet agent interactively from within this Claude Code session.

## Usage

```
/timesheet
/timesheet --dry-run
/timesheet --start 2026-06-23 --end 2026-06-30
/timesheet --list-projects
```

## What this command does

1. Loads the project mapping from `config/project_mapping.yaml`
2. Calls `agent/timesheet_agent.py` with the given arguments
3. Surfaces the draft timesheet inline in this session
4. Lets you approve, edit, or hold entries via conversational replies

## Running

```bash
python agent/timesheet_agent.py $ARGUMENTS
```

## Notes

- Requires `.env.local` with all six credentials populated
- Use `--dry-run` on first run to verify the mapping without sending any messages or writing to Kantata
- The draft is saved to `data/pending_timesheets.json` — safe to re-run if interrupted
