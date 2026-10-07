"""Ticket 03 audit demonstration from sanitized observed projections.

uv run python scripts/pi_audit_demo.py --json
uv run python scripts/pi_audit_demo.py
No upstream code is executed; temporary fixture sessions are not replays.
"""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from drskill.traces import evidence
from drskill.traces.pipeline import run_audit
from drskill.traces.report import render_audit
from pi_nested_demo import demonstrate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="pi-audit-demo-") as temporary:
        home = Path(temporary)
        sessions = home / ".pi/agent/sessions/project"
        sessions.mkdir(parents=True)
        demonstrate(sessions)
        data = run_audit(home, Path("/workspace"), True, "pi", None)
        counts = evidence.summary(data)
        assert counts["nested_read_occurrences"] == 9
        assert counts["nested_distinct_executions"] == 8
        assert counts["nested_inherited_occurrences"] == 1
        if args.json:
            print(json.dumps({
                "report_version": evidence.REPORT_VERSION,
                "qualification": "Sanitized observed projections plus one source-qualified synthetic bounds row",
                "evidence_summary": counts,
                **data.model_dump(mode="json"),
            }, indent=2))
        else:
            render_audit(Console(), data)


if __name__ == "__main__":
    main()
