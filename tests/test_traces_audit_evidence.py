"""Ticket 03 public cached-corpus and CLI regression seams."""
import json
from pathlib import Path

from drskill.traces.pipeline import run_audit


def session(home, name, entries, **header):
    path = home / ".pi/agent/sessions/project" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [{"type": "session", "id": name, "cwd": "/workspace", **header}, *entries]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def result(entry="r", path="skills/example/SKILL.md", parent=None, complete=True):
    return {"type": "message", "id": entry, "parentId": parent,
            "timestamp": "2026-10-07T00:00:00Z",
            "message": {"role": "toolResult", "toolName": "codemode", "isError": True,
                        "nestedCalls": {"complete": complete, "calls": [
                            {"id": "c", "name": "read", "status": "ok",
                             "arguments": {"path": path}}]}}}


def test_cached_corpus_retains_inherited_occurrences_and_one_execution(tmp_path):
    parent = session(tmp_path, "parent.jsonl", [result()])
    session(tmp_path, "child.jsonl", [result()], parentSession=str(parent))
    first = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    second = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    assert len(first.nested_reads) == len(second.nested_reads) == 2
    assert {r.execution_owner for r in second.nested_reads} == {
        ("parent.jsonl", "r", "c")}
    assert first.model_dump() == second.model_dump()
    assert second.evidence_scope == "all-retained-branches"


def test_cli_reports_outer_failure_read_and_unknown_coverage(tmp_path):
    from typer.testing import CliRunner
    from drskill.cli import app
    path = session(tmp_path, "main.jsonl", [result(complete=False)])
    runner = CliRunner()
    args = ["audit", "--file", str(path), "--harness", "pi"]
    machine = runner.invoke(app, [*args, "--json"])
    assert machine.exit_code == 0, machine.output
    payload = json.loads(machine.output)
    assert payload["evidence_summary"]["nested_read_occurrences"] == 1
    assert payload["evidence_summary"]["nested_distinct_executions"] == 1
    assert payload["nested_reads"][0]["requested_path"] == "skills/example/SKILL.md"
    assert payload["coverage_limits"]
    human = runner.invoke(app, args)
    assert human.exit_code == 0, human.output
    assert "physical occurrences" in human.output
    assert "unknown" in human.output


def wrapper():
    return {"type": "message", "id": "u", "parentId": None,
            "timestamp": "2026-10-07T00:00:00Z",
            "message": {"role": "user", "content": [
                {"type": "text", "text":
                 '<skill name="example" location="/workspace/skills/example/SKILL.md">\n'
                 'References are relative to /workspace/skills/example.\n'
                 'Read [guide](guide.md).\n</skill>'}]}}


def test_cli_preserves_delivery_skill_and_declared_support_without_double_count(tmp_path):
    from typer.testing import CliRunner
    from drskill.cli import app
    path = session(tmp_path, "main.jsonl", [
        wrapper(), result(parent="u"),
        result(entry="support", path="skills/example/guide.md", parent="r"),
        result(entry="unrelated", path="other.md", parent="support"),
    ])
    output = CliRunner().invoke(app, ["audit", "example", "--file", str(path),
                                     "--harness", "pi", "--json"])
    assert output.exit_code == 0, output.output
    payload = json.loads(output.output)
    counts = payload["evidence_summary"]
    assert counts["instruction_deliveries"] == 1
    assert counts["skill_file_reads"] == 1
    assert counts["supporting_reads"] == 1
    assert counts["combined_observed_uses"] == 1
    assert len(payload["nested_reads"]) == 2
    assert payload["invocations"][0]["source_line"] == 2
    assert payload["nested_reads"][0]["source_line"] == 3


def test_selected_branch_uses_raw_ancestry_and_rejects_missing_links(tmp_path):
    from drskill.traces.pipeline import run_audit_file
    import pytest
    path = session(tmp_path, "main.jsonl", [
        wrapper(), result(entry="left", parent="u"),
        result(entry="right", path="skills/other/SKILL.md", parent="u"),
    ])
    data = run_audit_file(tmp_path, path, "pi", None, branch="left")
    assert [r.occurrence[1] for r in data.nested_reads] == ["left"]
    assert data.evidence_scope == "selected-branch:left"
    with pytest.raises(ValueError, match="ancestry"):
        run_audit_file(tmp_path, path, "pi", None, branch="absent")


def test_cache_reconciles_removed_parent_and_keeps_unknown_historical_coverage(tmp_path):
    parent = session(tmp_path, "parent.jsonl", [result()])
    session(tmp_path, "child.jsonl", [result()], parentSession=str(parent))
    session(tmp_path, "old.jsonl", [{
        "type": "message", "id": "old", "parentId": None,
        "message": {"role": "toolResult", "toolName": "codemode", "isError": False,
                    "details": {"calls": [{"args": '{"path":"skills/fake/SKILL.md"}',
                                          "status": "ok"}]}}}])
    run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    parent.unlink()
    data = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    assert len(data.nested_reads) == 1
    assert data.nested_reads[0].execution_owner is None
    assert {"ancestry-missing-parent", "missing-structured-evidence", "capability-unknown"} <= {
        d.code for d in data.nested_diagnostics}
    assert data.coverage_limits


def test_cli_unknown_pi_coverage_prevents_unused_classification(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from drskill.cli import app
    monkeypatch.setenv("DRSKILL_HOME", str(tmp_path))
    session(tmp_path, "main.jsonl", [wrapper()])
    root = tmp_path / "repo"
    root.mkdir()
    payload = json.loads(CliRunner().invoke(app, [
        "audit", "--root", str(root), "--global", "--json"]).output)
    assert payload["unused"] is None
    assert payload["coverage_limits"]


def test_native_declared_support_is_retained_with_result_locator(tmp_path):
    from drskill.traces import pi
    user = wrapper()
    user["message"]["content"][0]["text"] = user["message"]["content"][0]["text"].replace(
        "/workspace/skills/example", "/workspace/.hidden/example")
    path = session(tmp_path, "native.jsonl", [
        user,
        {"type": "message", "id": "a", "parentId": "u",
         "timestamp": "2026-10-07T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "toolCall", "id": "read-1", "name": "read",
              "arguments": {"path": "/workspace/.hidden/example/guide.md"}}]}},
        {"type": "message", "id": "done", "parentId": "a",
         "message": {"role": "toolResult", "toolCallId": "read-1",
                     "toolName": "read", "isError": False}},
    ])
    extracted = pi.extract(path)
    support = [i for i in extracted.invocations if i.evidence_kind == "supporting-read"]
    assert len(support) == 1
    assert support[0].name == "example"
    assert support[0].result_entry_id == "done"
    assert support[0].source_line == 3
    assert support[0].result_source_line == 4


def test_duplicate_parent_result_never_certifies_new_child_execution(tmp_path):
    parent = session(tmp_path, "parent.jsonl", [result(), result()])
    session(tmp_path, "child.jsonl", [result()], parentSession=str(parent))
    data = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    assert len(data.nested_reads) == 1
    assert data.nested_reads[0].execution_owner is None
    assert any(d.code == "ancestry-invalid-ancestor-evidence" for d in data.nested_diagnostics)


def test_cached_pi_corpus_uses_no_session_rereads(tmp_path, monkeypatch):
    path = session(tmp_path, "main.jsonl", [result(complete=False)])
    run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    read_bytes = Path.read_bytes

    def forbid_session_read(file):
        if file == path:
            raise AssertionError("cache hit must not reopen session bytes")
        return read_bytes(file)

    monkeypatch.setattr(Path, "read_bytes", forbid_session_read)
    data = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    assert not data.unreadable
    assert len(data.nested_reads) == 1
    assert any(d.code == "incomplete-coverage" for d in data.nested_diagnostics)


def test_relative_explicit_file_and_untimed_since_are_qualified(tmp_path, monkeypatch):
    import datetime as dt
    from drskill.traces.pipeline import run_audit_file
    record = result()
    record.pop("timestamp")
    path = session(tmp_path, "main.jsonl", [record])
    monkeypatch.chdir(path.parent)
    data = run_audit_file(tmp_path, Path("main.jsonl"), "pi",
                          dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc))
    assert len(data.nested_reads) == 1
    assert data.nested_reads[0].result_record_time is None
    assert any("Untimed" in limit for limit in data.coverage_limits)


def test_combined_summary_does_not_include_other_harnesses(tmp_path):
    import datetime as dt
    from drskill.traces.evidence import summary
    from drskill.traces.model import Invocation
    from drskill.traces.pipeline import AuditData
    data = AuditData(invocations=[Invocation(
        harness="claude-code", session_id="s", timestamp=dt.datetime.now(dt.timezone.utc),
        kind="skill", name="example", detection="explicit", source_file="claude.jsonl")])
    assert summary(data)["combined_observed_uses"] == 0


def test_non_pi_drift_preserves_existing_unused_report(tmp_path, monkeypatch):
    import datetime as dt
    from typer.testing import CliRunner
    from drskill.cli import app
    monkeypatch.setenv("DRSKILL_HOME", str(tmp_path))
    root = tmp_path / "repo"
    skill = root / ".claude/skills/unused-example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: unused-example\ndescription: demo\n---\nbody\n")
    traces = tmp_path / ".claude/projects/project"
    traces.mkdir(parents=True)
    timestamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=100)).isoformat()
    (traces / "valid.jsonl").write_text(json.dumps({
        "type": "assistant", "sessionId": "claude", "timestamp": timestamp,
        "cwd": str(root), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "c", "name": "Skill", "input": {"skill": "used"}}
        ]}}) + "\n")
    (traces / "drift.jsonl").write_text('{"type":"unknown"}\n')
    response = CliRunner().invoke(app, ["audit", "--root", str(root), "--json"])
    assert response.exit_code == 0, response.output
    payload = json.loads(response.output)
    assert payload["drifted"] == {"claude-code": 1}
    assert payload["coverage_limits"] == []
    assert any(row["name"] == "unused-example" for row in payload["unused"])


def test_native_duplicate_id_across_tool_names_cannot_certify_read(tmp_path):
    from drskill.traces import pi
    path = session(tmp_path, "native.jsonl", [
        {"type": "message", "id": "a", "parentId": None,
         "timestamp": "2026-10-07T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "toolCall", "id": "same", "name": "read",
              "arguments": {"path": "skills/example/SKILL.md"}},
             {"type": "toolCall", "id": "same", "name": "bash",
              "arguments": {"command": "true"}}]}},
        {"type": "message", "id": "done", "parentId": "a",
         "message": {"role": "toolResult", "toolCallId": "same",
                     "toolName": "read", "isError": False}},
    ])
    extracted = pi.extract(path)
    assert not extracted.invocations
    assert any(d.code == "native-read-unresolved" for d in extracted.nested_diagnostics)


def test_forked_delivery_and_nested_read_count_one_combined_use(tmp_path):
    from drskill.traces.evidence import summary
    parent = session(tmp_path, "parent.jsonl", [wrapper(), result(parent="u")])
    session(tmp_path, "child.jsonl", [wrapper(), result(parent="u")], parentSession=str(parent))
    data = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    counts = summary(data)
    assert counts["instruction_deliveries"] == 2
    assert counts["nested_read_occurrences"] == 2
    assert counts["nested_distinct_executions"] == 1
    assert counts["combined_observed_uses"] == 1


def test_native_fork_preserves_occurrences_and_distinct_executions(tmp_path):
    from drskill.traces.evidence import summary
    from drskill.traces.report import aggregate
    call = {"type": "message", "id": "a", "parentId": "u",
            "timestamp": "2026-10-07T00:00:01Z",
            "message": {"role": "assistant", "content": [
                {"type": "toolCall", "id": "read-1", "name": "read",
                 "arguments": {"path": "skills/example/SKILL.md"}}]}}
    done = {"type": "message", "id": "done", "parentId": "a",
            "message": {"role": "toolResult", "toolCallId": "read-1",
                        "toolName": "read", "isError": False}}
    parent = session(tmp_path, "parent.jsonl", [wrapper(), call, done])
    session(tmp_path, "child.jsonl", [wrapper(), call, done], parentSession=str(parent))
    data = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    counts = summary(data)
    assert counts["native_read_occurrences"] == 2
    assert counts["native_distinct_read_executions"] == 1
    assert counts["combined_observed_uses"] == 1
    assert aggregate(data.invocations)["pi"][0].count == 1
    parent.unlink()
    unresolved = run_audit(tmp_path, Path("/workspace"), False, "pi", None)
    assert summary(unresolved)["native_distinct_read_executions"] == 0
    assert summary(unresolved)["combined_observed_uses"] == 0
