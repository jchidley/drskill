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
