"""Observed projections and explicitly synthetic regressions at Pi extract(Path)."""
import json
import pytest
from pathlib import Path

from drskill.traces import pi

FIXTURES = Path(__file__).parent / "fixtures" / "pi-nested"


def write_session(tmp_path, header, entries, name="main.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in [header, *entries]) + "\n")
    return path


def test_observed_reads_preserve_request_identity_and_outer_failure(tmp_path):
    fixture = json.loads((FIXTURES / "observed-execution.json").read_text())
    entries = [dict(case["entry"], evidenceSource=case["source"]) for case in fixture["cases"]]
    result = pi.extract(write_session(tmp_path, fixture["session"], entries))
    assert len(result.nested_reads) == 5
    support = result.nested_reads[1]
    assert support.requested_path == "docs/agents/issue-tracker.md"
    assert support.resolved_path == "/workspace/docs/agents/issue-tracker.md"
    assert support.occurrence == ("session-main", "success", "success/call/2")
    assert support.result_record_time == "2026-10-07T00:00:00.000Z"
    assert support.provenance["entryId"] == "bf609a4d"
    assert result.nested_reads[-1].resolved_path == "/workspace/skills/implement/SKILL.md"
    assert len(result.nested_reads[-1].requested_path) > 200
    assert result.invocations == []
    assert sum(d.code == "read-error" for d in result.nested_diagnostics) == 2


def synthetic_result(calls, complete=True, **extra):
    return {"type": "message", "id": "result", "timestamp": "2026-10-07T00:00:00Z",
            "message": {"role": "toolResult", "toolName": "codemode", "isError": False,
                        "nestedCalls": {"calls": calls, "complete": complete}, **extra}}


def read_row(call_id="call/1", **extra):
    return {"id": call_id, "name": "read", "status": "ok",
            "arguments": {"path": "skills/example/SKILL.md"}, **extra}


@pytest.mark.parametrize("row", [
    read_row(status="error"), read_row(status="unfinished"), read_row(status="running"),
    read_row(status=None), read_row(id=""), read_row(arguments={}),
    read_row(arguments={"path": ""}), read_row(arguments={"path": 4}),
    read_row(arguments=None, argumentsBytes=8193),
])
def test_synthetic_incomplete_rows_never_certify_success(tmp_path, row):
    result = pi.extract(write_session(tmp_path, {"type": "session", "id": "s", "cwd": "/workspace"},
        [synthetic_result([row], complete=False,
                         details={"calls": [{"args": '{"path":"/preview/SKILL.md"}', "status": "ok"}]})]))
    assert result.nested_reads == []
    assert "incomplete-coverage" in [d.code for d in result.nested_diagnostics]


def test_synthetic_complete_rows_survive_recorder_bounds(tmp_path):
    # 256 retained calls with omitted >8KiB arguments and aggregate >32KiB loss.
    rows = [read_row(f"call/{i}", arguments=None, argumentsBytes=8193) for i in range(255)]
    rows.append(read_row("call/256", arguments={"path": "./skills/example/SKILL.md", "limit": 10}))
    result = pi.extract(write_session(tmp_path, {"type": "session", "id": "s", "cwd": "/workspace"},
                                         [synthetic_result(rows, complete=False)]))
    assert len(result.nested_reads) == 1
    assert result.nested_reads[0].resolved_path == "/workspace/skills/example/SKILL.md"
    assert "Partial read requested via offset/limit" in result.nested_reads[0].qualifications
    assert any("32 KiB" in d.detail for d in result.nested_diagnostics)


@pytest.mark.parametrize("path,cwd,expected", [
    ("~/skills/a/SKILL.md", "/workspace", None),
    ("@/skills/a/SKILL.md", "/workspace", None),
    ("C:\\skills\\a\\SKILL.md", "/workspace", None),
    ("relative/SKILL.md", None, None),
    ("/workspace/./a/../SKILL.md", None, "/workspace/SKILL.md"),
])
def test_synthetic_path_qualification(tmp_path, path, cwd, expected):
    result = pi.extract(write_session(tmp_path, {"type": "session", "id": "s", "cwd": cwd},
        [synthetic_result([read_row(arguments={"path": path})])]))
    [row] = result.nested_reads
    assert row.requested_path == path
    assert row.resolved_path == expected


def test_synthetic_malformed_outer_record_does_not_hide_valid_read(tmp_path):
    result = pi.extract(write_session(tmp_path, {"type": "session", "id": "s", "cwd": "/workspace"},
        [{"type": "message", "message": ["malformed"]}, synthetic_result([read_row()])]))
    assert len(result.nested_reads) == 1


def test_synthetic_duplicate_identity_is_unresolved(tmp_path):
    result = pi.extract(write_session(tmp_path, {"type": "session", "id": "s"},
        [synthetic_result([read_row(), read_row()])]))
    assert result.nested_reads == []
    assert any(d.code == "invalid-read-evidence" for d in result.nested_diagnostics)


def test_synthetic_missing_metadata_is_unknown_not_no_use(tmp_path):
    event = synthetic_result([])
    del event["message"]["nestedCalls"]
    result = pi.extract(write_session(tmp_path, {"type": "session", "id": "s", "version": 3}, [event]))
    assert result.nested_reads == []
    assert {d.code for d in result.nested_diagnostics} == {
        "missing-structured-evidence", "capability-unknown"}


def observed_boundary_sessions(tmp_path):
    fixture = json.loads((FIXTURES / "observed-session-boundaries.json").read_text())
    fork = fixture["cases"][1]
    parent = tmp_path / "parent.jsonl"
    child = tmp_path / "fork.jsonl"
    paths = []
    for header, occurrence, name in zip(fork["headers"], fork["occurrences"], ["parent.jsonl", "fork.jsonl"]):
        header = dict(header)
        if "parentSession" in header:
            header["parentSession"] = str(parent)
        paths.append(write_session(tmp_path, header,
            [dict(occurrence["entry"], evidenceSource=fork["source"])], name))
    standalone = fixture["cases"][2]
    paths.append(write_session(tmp_path, standalone["header"],
        [dict(standalone["entry"], evidenceSource=standalone["source"])], "standalone.jsonl"))
    return paths


def test_observed_corpus_fork_and_standalone(tmp_path):
    from drskill.traces.pipeline import extract_pi_nested_corpus
    paths = observed_boundary_sessions(tmp_path)
    result = extract_pi_nested_corpus(list(reversed(paths)))
    assert len(result.nested_reads) == 3
    assert len({r.execution_owner for r in result.nested_reads}) == 2
    fork = next(r for r in result.nested_reads if r.occurrence[0] == "session-fork")
    assert fork.inheritance == "inherited"
    assert fork.execution_owner == ("session-parent", "inherited-result", "ancestor-call/1")
    standalone = next(r for r in result.nested_reads if r.occurrence[0] == "session-child")
    assert standalone.inheritance == "independent"
    assert standalone.result_record_time is None


@pytest.mark.parametrize("case", ["missing-parent", "missing-child", "conflict", "cycle", "unrelated"])
def test_synthetic_corpus_does_not_guess_ancestry(tmp_path, case):
    from drskill.traces.pipeline import extract_pi_nested_corpus
    paths = observed_boundary_sessions(tmp_path)[:2]
    if case == "missing-parent":
        paths = paths[1:]
    elif case == "missing-child":
        paths[1].unlink()
    elif case == "conflict":
        events = [json.loads(line) for line in paths[1].read_text().splitlines()]
        events[1]["message"]["nestedCalls"]["calls"][0]["arguments"]["path"] = "/different/SKILL.md"
        write_session(tmp_path, events[0], events[1:], "fork.jsonl")
    elif case == "cycle":
        events = [json.loads(line) for line in paths[0].read_text().splitlines()]
        events[0]["parentSession"] = str(paths[1])
        write_session(tmp_path, events[0], events[1:], "parent.jsonl")
    else:
        events = [json.loads(line) for line in paths[1].read_text().splitlines()]
        del events[0]["parentSession"]
        write_session(tmp_path, events[0], events[1:], "fork.jsonl")
    result = extract_pi_nested_corpus(paths)
    if case == "unrelated":
        assert all(r.inheritance == "independent" for r in result.nested_reads)
        assert len({r.execution_owner for r in result.nested_reads}) == 2
    elif case == "missing-child":
        assert any(d.code == "missing-session" for d in result.nested_diagnostics)
    else:
        assert any(r.inheritance == "unresolved" for r in result.nested_reads)
        assert any(d.code.startswith("ancestry-") for d in result.nested_diagnostics)
