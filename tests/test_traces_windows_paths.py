"""Windows lexical paths through the agreed extraction and audit seams."""
import json
from pathlib import Path

import pytest

from drskill.traces import pi


def session(tmp_path, cwd, requested):
    path = tmp_path / "windows.jsonl"
    records = [
        {"type": "session", "id": "windows", "cwd": cwd},
        {"type": "message", "id": "r", "parentId": None,
         "timestamp": "2026-10-07T00:00:00Z",
         "evidenceSource": {"label": "synthetic regression"},
         "message": {"role": "toolResult", "toolName": "codemode", "isError": True,
                     "nestedCalls": {"complete": True, "calls": [
                         {"id": "c", "name": "read", "status": "ok",
                          "arguments": {"path": requested, "limit": 10}}]}}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


@pytest.mark.parametrize("requested,cwd,expected", [
    (r"c:\Skills\example\..\other\SKILL.md", None, "C:/Skills/other/SKILL.md"),
    ("C:/Skills/./example/SKILL.md", "/workspace", "C:/Skills/example/SKILL.md"),
    (r"skills\example\SKILL.md", r"D:\Work\project", "D:/Work/project/skills/example/SKILL.md"),
    ("../skills/example/SKILL.md", "D:/Work/project", "D:/Work/skills/example/SKILL.md"),
    (r"\\server\share\skills\example\..\other\SKILL.md", None, "//server/share/skills/other/SKILL.md"),
    (r".\SKILL.md", r"\\server\share\skills\example", "//server/share/skills/example/SKILL.md"),
    (r"C:skills\example\SKILL.md", "C:/Work", None),
    (r"\skills\example\SKILL.md", "C:/Work", None),
    ("/mnt/c/skills/example/SKILL.md", "C:/Work", None),
    (r"skills\example\SKILL.md", "/workspace", None),
    (r"\\?\C:\skills\example\SKILL.md", None, None),
    (r"\\.\C:\skills\example\SKILL.md", None, None),
    ("//?/UNC/server/share/SKILL.md", None, None),
    ("~/skills/example/SKILL.md", "C:/Work", None),
    ("file:///C:/skills/example/SKILL.md", "C:/Work", None),
    ("relative/SKILL.md", r"\\?\C:\Work", None),
    ("relative/SKILL.md", "//?/C:/Work", None),
    ("relative/SKILL.md", "//./C:/Work", None),
    ("/workspace/./skills/example/SKILL.md", "/workspace", "/workspace/skills/example/SKILL.md"),
])
def test_recorded_namespaces_resolve_without_host_or_cross_os_guessing(tmp_path, requested, cwd, expected):
    [row] = pi.extract(session(tmp_path, cwd, requested)).nested_reads
    assert row.resolved_path == expected
    assert row.requested_path == requested
    if expected is None:
        assert any("nresolved" in q for q in row.qualifications)


def windows_workflow(tmp_path, base="C:/Skills/example"):
    path = session(tmp_path, "C:/Work", base + "/SKILL.md")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    wrapper = {"type": "message", "id": "u", "parentId": None,
               "timestamp": "2026-10-07T00:00:00Z",
               "message": {"role": "user", "content":
                   f'<skill name="example" location="{base}/SKILL.md">\n'
                   f'References are relative to {base}.\n'
                   'Read [guide](docs/guide.md).\n</skill>'}}
    records[1]["parentId"] = "u"
    records.insert(1, wrapper)
    support = json.loads(json.dumps(records[-1]))
    support["id"] = "support"
    support["parentId"] = "r"
    support["message"]["nestedCalls"]["calls"][0]["arguments"] = {
        "path": base.replace("/", "\\") + r"\docs\guide.md"}
    records.append(support)
    records.extend([
        {"type": "message", "id": "a", "parentId": "support",
         "timestamp": "2026-10-07T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "toolCall", "id": "native", "name": "read",
              "arguments": {"path": base.replace("/", "\\") + r"\SKILL.md"}}]}},
        {"type": "message", "id": "done", "parentId": "a",
         "timestamp": "2026-10-07T00:00:02Z",
         "message": {"role": "toolResult", "toolCallId": "native",
                     "toolName": "read", "isError": False}},
    ])
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


@pytest.mark.parametrize("base", ["C:/Skills/example", r"C:\Skills\example", "//server/share/Skills/example"])
def test_windows_wrapper_native_and_nested_reads_are_qualified_and_deduplicated(tmp_path, base):
    from typer.testing import CliRunner
    from drskill.cli import app
    path = windows_workflow(tmp_path, base)
    args = ["audit", "--file", str(path), "--harness", "pi"]
    machine = CliRunner().invoke(app, [*args, "--json"])
    assert machine.exit_code == 0, machine.output
    payload = json.loads(machine.output)
    assert payload["evidence_summary"]["instruction_deliveries"] == 1
    assert payload["evidence_summary"]["skill_file_reads"] == 2
    assert payload["evidence_summary"]["supporting_reads"] == 1
    assert payload["evidence_summary"]["combined_observed_uses"] == 1
    assert payload["report_version"] == 3
    assert payload["extraction_versions"]["pi"] == 12
    assert payload["nested_reads"][1]["evidence_kind"] == "supporting-read"
    assert payload["invocations"][1]["result_entry_id"] == "done"
    human = CliRunner().invoke(app, args)
    assert human.exit_code == 0, human.output
    assert "Windows lexical namespace" in human.output
    assert "report 3" in human.output
    assert "Pi extraction 12" in human.output


def test_case_mismatch_and_cross_os_paths_never_certify_same_resource(tmp_path):
    from drskill.traces.pipeline import run_audit_file
    from drskill.traces.evidence import summary
    path = windows_workflow(tmp_path)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    calls = records[2]["message"]["nestedCalls"]["calls"]
    calls[0]["arguments"]["path"] = "c:/skills/example/SKILL.md"
    calls.extend([
        {"id": "posix", "name": "read", "status": "ok",
         "arguments": {"path": "/mnt/c/Skills/example/SKILL.md"}},
        {"id": "lower", "name": "read", "status": "ok",
         "arguments": {"path": "C:/Skills/example/skill.md"}},
        {"id": "failed", "name": "read", "status": "error",
         "arguments": {"path": "C:/Skills/example/SKILL.md"}},
        {"id": "pending", "name": "read", "status": "running",
         "arguments": {"path": "C:/Skills/example/SKILL.md"}},
    ])
    records[3]["message"]["nestedCalls"]["calls"][0]["arguments"]["path"] = "C:/skills/example/docs/guide.md"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    data = run_audit_file(tmp_path, path, "pi", None)
    assert len(data.nested_reads) == 4
    assert data.nested_reads[0].combined_use_id is None
    assert data.nested_reads[1].resolved_path is None
    assert data.nested_reads[2].evidence_kind is None
    assert data.nested_reads[3].evidence_kind is None
    assert summary(data)["combined_observed_uses"] == 2


def test_windows_cached_fork_uses_owner_context_and_reextracts_old_cache(tmp_path):
    from drskill.traces.pipeline import run_audit
    from drskill.traces.evidence import summary
    from drskill.traces.cache import audit_cache_dir
    directory = tmp_path / ".pi/agent/sessions/project"
    directory.mkdir(parents=True)
    parent = windows_workflow(directory)
    records = [json.loads(line) for line in parent.read_text().splitlines()]
    # Make the nested skill path relative to the recorded Windows cwd.
    records[0]["cwd"] = "C:/Skills"
    records[2]["message"]["nestedCalls"]["calls"][0]["arguments"]["path"] = r"example\SKILL.md"
    parent.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    records[0].update(id="fork", cwd="/different", parentSession=str(parent))
    child = directory / "child.jsonl"
    child.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    first = run_audit(tmp_path, Path("/workspace"), True, "pi", None)
    second = run_audit(tmp_path, Path("/workspace"), True, "pi", None)
    assert first.model_dump() == second.model_dump()
    inherited = next(r for r in second.nested_reads if r.occurrence[:2] == ("fork", "r"))
    assert inherited.resolved_path == "C:/Skills/example/SKILL.md"
    assert inherited.inheritance == "inherited"
    assert summary(second)["combined_observed_uses"] == 1
    # Mutate the serialized public cache artifact, not an internal collaborator.
    cache_files = list(audit_cache_dir(tmp_path).glob("*.json"))
    assert cache_files
    for file in cache_files:
        payload = json.loads(file.read_text())
        payload["adapter_version"] = 11
        payload["pi_evidence"]["nested_reads"] = []
        file.write_text(json.dumps(payload))
    refreshed = run_audit(tmp_path, Path("/workspace"), True, "pi", None)
    assert refreshed.model_dump() == first.model_dump()


def test_mixed_absolute_posix_and_windows_reads_keep_distinct_namespaces(tmp_path):
    from drskill.traces.pipeline import run_audit_file
    from drskill.traces.evidence import summary
    path = session(tmp_path, "/workspace", "C:/skills/example/SKILL.md")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[1]["message"]["nestedCalls"]["calls"].append({
        "id": "posix", "name": "read", "status": "ok",
        "arguments": {"path": "/mnt/c/skills/example/SKILL.md"}})
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    data = run_audit_file(tmp_path, path, "pi", None)
    assert [r.resolved_path for r in data.nested_reads] == [
        "C:/skills/example/SKILL.md", "/mnt/c/skills/example/SKILL.md"]
    assert summary(data)["combined_observed_uses"] == 2


def test_windows_absolute_read_preserves_recorded_evidence(tmp_path):
    requested = r"C:\Skills\example\.\docs\..\SKILL.md"
    [row] = pi.extract(session(tmp_path, "/workspace", requested)).nested_reads
    assert row.resolved_path == "C:/Skills/example/SKILL.md"
    assert row.requested_path == requested
    assert row.occurrence == ("windows", "r", "c")
    assert row.result_record_time == "2026-10-07T00:00:00Z"
    assert row.provenance == {"label": "synthetic regression"}
    assert "Partial read requested via offset/limit" in row.qualifications
    assert any("Windows" in q and "case-sensitive" in q for q in row.qualifications)
