"""Runnable, content-free observed-fixture demonstration for ticket 03.

Run from repository root: uv run python scripts/pi_nested_demo.py
All temporary sessions are projections, not replays of real sessions.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from drskill.traces.pipeline import extract_pi_nested_corpus

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pi-nested"


def demonstrate(directory: Path):
    def write(name, header, entries):
        path = directory / name
        path.write_text("\n".join(json.dumps(e) for e in [header, *entries]) + "\n")
        return path

    execution = json.loads((FIXTURES / "observed-execution.json").read_text())
    boundaries = json.loads((FIXTURES / "observed-session-boundaries.json").read_text())
    paths = [write("main.jsonl", execution["session"],
                   [dict(c["entry"], evidenceSource=dict(c["source"], fixtureKind="observed",
                         fixtureCase=c["id"])) for c in execution["cases"]])]
    fork = boundaries["cases"][1]
    for header, occurrence, name in zip(fork["headers"], fork["occurrences"],
                                        ["parent.jsonl", "fork.jsonl"]):
        header = dict(header)
        if "parentSession" in header:
            header["parentSession"] = str(directory / "parent.jsonl")
        paths.append(write(name, header, [dict(occurrence["entry"],
            evidenceSource=dict(fork["source"], fixtureKind="observed", fixtureCase=fork["id"]))]))
    child = boundaries["cases"][2]
    paths.append(write("standalone.jsonl", child["header"],
        [dict(child["entry"], evidenceSource=dict(child["source"], fixtureKind="observed",
                                                fixtureCase=child["id"]))]))
    # Source-qualified synthetic recorder-loss case, not an executed overflow probe.
    calls = [{"id": f"bounded/{i}", "name": "read", "status": "ok",
              "argumentsBytes": 8193} for i in range(255)]
    calls.append({"id": "bounded/255", "name": "read", "status": "ok",
                  "arguments": {"path": "./skills/example/SKILL.md", "limit": 20}})
    paths.append(write("synthetic-bounds.jsonl", {"type": "session", "id": "synthetic", "cwd": "/workspace"},
        [{"type": "message", "id": "bounded", "timestamp": "2026-10-07T00:00:00Z",
          "evidenceSource": {"fixtureKind": "synthetic", "fixtureCase": "recorder-bounds"},
          "message": {"role": "toolResult", "toolName": "codemode",
                      "nestedCalls": {"complete": False, "calls": calls}}}]))
    result = extract_pi_nested_corpus(paths)
    return {
        "scope": "All raw branches of explicitly supplied projected sessions; no audit integration",
        "qualification": "Observed projections are sanitized; synthetic bounds are source-qualified, not observed",
        "summary": {
            "successful_read_occurrences": len(result.nested_reads),
            "resolved_executions": len({r.execution_owner for r in result.nested_reads if r.execution_owner}),
            "inherited_occurrences": sum(r.inheritance == "inherited" for r in result.nested_reads),
            "unresolved_occurrences": sum(r.inheritance == "unresolved" for r in result.nested_reads),
        },
        **result.model_dump(exclude={"invocations", "recognized"}),
    }


if __name__ == "__main__":
    with TemporaryDirectory(prefix="pi-nested-demo-") as directory:
        print(json.dumps(demonstrate(Path(directory)), indent=2))
