"""
export_skill.py — Package the timesheet agent as a Claude Code .skill file.

Usage:
    python scripts/export_skill.py --output kantata-timesheet.skill
"""

import argparse
import json
import zipfile
from pathlib import Path

SKILL_FILES = [
    "agent/timesheet_agent.py",
    "mcp/calendar_connector.py",
    "mcp/kantata_connector.py",
    "config/project_mapping.yaml",
    ".claude/commands/timesheet.md",
    "CLAUDE.md",
    "README.md",
    "requirements.txt",
    ".env.example",
]

MANIFEST = {
    "name": "kantata-timesheet-agent",
    "version": "0.1.0",
    "description": "Auto-draft and submit Kantata timesheets from Outlook calendar events",
    "author": "PI Partners <festella@pipartners.com>",
    "entry": "agent/timesheet_agent.py",
    "commands": [".claude/commands/timesheet.md"],
}


def export_skill(output_path: str) -> None:
    out = Path(output_path)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(MANIFEST, indent=2))
        for rel_path in SKILL_FILES:
            p = Path(rel_path)
            if p.exists():
                zf.write(p, rel_path)
            else:
                print(f"Warning: {rel_path} not found, skipping")
    print(f"Skill exported to: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="kantata-timesheet.skill")
    args = parser.parse_args()
    export_skill(args.output)
