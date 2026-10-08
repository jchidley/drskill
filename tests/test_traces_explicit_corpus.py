"""Ticket 04: explicitly supplied corpus and existing report seams."""
import datetime as dt
import json

from tests.test_traces_audit_evidence import session, result
from drskill.traces import pipeline
from drskill.traces.evidence import summary

START = dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)


def test_explicit_disjoint_corpus_uses_one_half_open_window(tmp_path):
    untimed = result(entry="untimed")
    untimed.pop("timestamp")
    outside = result(entry="outside")
    outside["timestamp"] = "2026-10-08T00:00:00Z"
    win = session(tmp_path, "win.jsonl", [result(), outside, untimed],
                  cwd="C:\\work", os="win32", version=3)
    wsl = session(tmp_path, "wsl.jsonl", [result()], cwd="/work")
    session(tmp_path, "unrequested.jsonl", [result()])
    data = pipeline.run_audit_files(tmp_path, [win, wsl], "pi", START, END)
    assert len(data.inspected_files) == 2
    assert len(data.nested_reads) == 3
    assert summary(data)["combined_observed_uses"] == 3
    assert data.window["until"] == END.isoformat()
    assert data.sources[str(win.resolve())]["recorded_os"] == "win32"
    assert data.sources[str(wsl.resolve())]["recorded_os"] is None
    assert data.sources[str(win.resolve())]["inspected_nested_reads"] == 3
    assert any("Untimed" in limit for limit in data.coverage_limits)


def test_declared_cross_location_copy_and_cache_removal(tmp_path):
    parent = session(tmp_path, "exported-parent.jsonl", [result()], cwd="C:\\work")
    child = session(tmp_path, "child.jsonl", [result()], cwd="/relocated",
                    parentSession="C:\\sessions\\parent.jsonl")
    locations = {str(parent): "C:\\sessions\\parent.jsonl"}
    data = pipeline.run_audit_files(tmp_path, [parent, child], "pi", START, END,
                                    source_locations=locations)
    assert summary(data)["nested_distinct_executions"] == 1
    assert summary(data)["nested_inherited_occurrences"] == 1
    inherited = next(r for r in data.nested_reads if r.source_file == str(child))
    assert inherited.resolved_path == "C:/work/skills/example/SKILL.md"
    assert inherited.project == "/relocated"
    cached = pipeline.run_audit_files(tmp_path, [parent, child], "pi", START, END,
                                      source_locations=locations)
    assert cached.model_dump() == data.model_dump()
    removed = pipeline.run_audit_files(tmp_path, [child], "pi", START, END)
    assert removed.nested_reads[0].execution_owner is None
    assert any(d.code == "ancestry-missing-parent" for d in removed.nested_diagnostics)
    assert summary(removed)["combined_observed_uses"] == 0


def test_cli_repeated_files_report_per_source_and_aggregate(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from drskill.cli import app
    monkeypatch.setenv("DRSKILL_HOME", str(tmp_path))
    win = session(tmp_path, "win.jsonl", [result(path="skills/example/SKILL.md")],
                  cwd="C:\\work")
    wsl = session(tmp_path, "wsl.jsonl", [result()], cwd="/work")
    args = ["audit", "--harness", "pi", "--file", str(win), "--file", str(wsl),
            "--since", "2026-10-07T00:00:00Z", "--until", "2026-10-08T00:00:00Z"]
    machine = CliRunner().invoke(app, [*args, "--json"])
    assert machine.exit_code == 0, machine.output
    payload = json.loads(machine.output)
    assert len(payload["inspected_files"]) == 2
    assert payload["evidence_summary"]["combined_observed_uses"] == 2
    assert payload["source_summaries"][str(win)]["combined_observed_uses"] == 1
    assert payload["nested_reads"][0]["result_record_time"] == "2026-10-07T00:00:00Z"
    human = CliRunner().invoke(app, args)
    assert human.exit_code == 0, human.output
    assert "Window:" in human.output
    assert "windows" in human.output
    assert "inspected" in human.output
    assert "Combined observed uses: 2" in human.output


def test_native_and_delivery_untimed_rows_survive_result_time_window(tmp_path):
    from tests.test_traces_audit_evidence import wrapper
    user = wrapper()
    user.pop("timestamp")
    call = {"type": "message", "id": "a", "parentId": "u",
            "timestamp": "2026-10-06T00:00:00Z",
            "message": {"role": "assistant", "content": [
                {"type": "toolCall", "id": "read-1", "name": "read",
                 "arguments": {"path": "skills/example/SKILL.md"}}]}}
    done = {"type": "message", "id": "done", "parentId": "a",
            "timestamp": "2026-10-07T01:00:00Z",
            "message": {"role": "toolResult", "toolCallId": "read-1",
                        "toolName": "read", "isError": False}}
    path = session(tmp_path, "native.jsonl", [user, call, done])
    data = pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
    assert len(data.invocations) == 2
    assert data.invocations[0].timestamp is None
    read = next(i for i in data.invocations if i.result_entry_id)
    assert read.result_record_time == "2026-10-07T01:00:00Z"
    assert read.window_membership == "inside"
    assert data.invocations[0].window_membership == "unknown"
    done.pop("timestamp")
    path = session(tmp_path, "native.jsonl", [user, call, done])
    untimed = pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
    assert len(untimed.invocations) == 2
    assert all(i.window_membership == "unknown" for i in untimed.invocations)


def test_conflicting_payload_and_same_id_sources_never_collapse(tmp_path):
    parent = session(tmp_path, "parent.jsonl", [result()])
    child = session(tmp_path, "child.jsonl", [result(path="skills/other/SKILL.md")],
                    parentSession=str(parent))
    conflicting = pipeline.run_audit_files(tmp_path, [parent, child], "pi", START, END)
    assert summary(conflicting)["nested_unresolved_occurrences"] == 1
    assert any(d.code == "ancestry-conflicting-payload" for d in conflicting.nested_diagnostics)
    same_id = session(tmp_path, "same-id.jsonl", [result()], id="parent.jsonl")
    ambiguous = pipeline.run_audit_files(tmp_path, [parent, same_id], "pi", START, END)
    assert summary(ambiguous)["nested_distinct_executions"] == 0
    assert len(ambiguous.nested_reads) == 2


def test_ambiguous_recorded_location_never_selects_an_ancestor(tmp_path):
    parent = session(tmp_path, "parent.jsonl", [result()])
    other = session(tmp_path, "other.jsonl", [result()])
    child = session(tmp_path, "child.jsonl", [result()],
                    parentSession="C:/sessions/parent.jsonl")
    locations = {str(parent): "C:/sessions/parent.jsonl",
                 str(other): "C:/sessions/parent.jsonl"}
    data = pipeline.run_audit_files(tmp_path, [parent, other, child], "pi", START, END,
                                    source_locations=locations)
    row = next(r for r in data.nested_reads if r.source_file == str(child))
    assert row.execution_owner is None
    assert any(d.code == "ancestry-ambiguous-parent" for d in data.nested_diagnostics)


def test_outside_window_wrapper_still_qualifies_windows_supporting_read(tmp_path):
    from tests.test_traces_audit_evidence import wrapper
    user = wrapper()
    user["timestamp"] = "2026-10-06T00:00:00Z"
    user["message"]["content"][0]["text"] = (
        '<skill name="example" location="C:/Skills/example/SKILL.md">\n'
        'References are relative to C:/Skills/example.\n'
        'Read [guide](guide.md).\n</skill>')
    support = result(path="C:\\Skills\\example\\guide.md", parent="u")
    path = session(tmp_path, "win.jsonl", [user, support], cwd="C:/work")
    data = pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
    assert not data.invocations
    assert data.nested_reads[0].evidence_kind == "supporting-read"
    assert summary(data)["combined_observed_uses"] == 0


def test_same_name_resources_are_separate_in_human_inventory_view(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from drskill.cli import app
    monkeypatch.setenv("DRSKILL_HOME", str(tmp_path))
    a = session(tmp_path, "a.jsonl", [result(path="C:/v1/example/SKILL.md")])
    b = session(tmp_path, "b.jsonl", [result(path="/v2/example/SKILL.md")])
    output = CliRunner().invoke(app, ["audit", "--harness", "pi",
                                     "--file", str(a), "--file", str(b)])
    assert output.exit_code == 0, output.output
    assert "C:/v1/example/SKILL.md" in output.output
    assert "/v2/example/SKILL.md" in output.output
    assert "not joined to current inventory" in output.output


def test_explicit_cache_hits_and_incompatible_contract_reextract(tmp_path, monkeypatch):
    from pathlib import Path
    path = session(tmp_path, "main.jsonl", [result()])
    pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
    original = Path.read_bytes
    def forbid_session_read(p):
        if p == path:
            raise AssertionError("cache hit reopened a supplied session")
        return original(p)
    with monkeypatch.context() as context:
        context.setattr(Path, "read_bytes", forbid_session_read)
        cached = pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
        assert len(cached.nested_reads) == 1
    cache_file = next((tmp_path / ".drskill/cache/audit").glob("*.json"))
    payload = json.loads(cache_file.read_text())
    payload["cache_version"] = 1
    payload["pi_evidence"]["nested_reads"] = []
    cache_file.write_text(json.dumps(payload))
    fresh = pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
    assert len(fresh.nested_reads) == 1


def test_cli_rejects_unbounded_ancestry_mapping_and_invalid_policy(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from drskill.cli import app
    monkeypatch.setenv("DRSKILL_HOME", str(tmp_path))
    a = session(tmp_path, "a.jsonl", [result()])
    b = session(tmp_path, "b.jsonl", [result()])
    base = ["audit", "--harness", "pi", "--file", str(a)]
    for extra in (
        ["--file", str(b), "--branch", "r"],
        ["--since", "2026-10-08", "--until", "2026-10-07"],
        ["--until", "2026-10-07T01:00:00"],
        ["--source-location", str(b) + "=C:/not-supplied.jsonl"],
    ):
        rejected = CliRunner().invoke(app, [*base, *extra])
        assert rejected.exit_code == 1, rejected.output


def test_untimed_activity_does_not_get_an_invented_weekly_rate(tmp_path):
    from tests.test_traces_audit_evidence import wrapper
    from drskill.traces.report import rollup
    user = wrapper()
    user.pop("timestamp")
    path = session(tmp_path, "untimed.jsonl", [user])
    data = pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
    assert rollup(data.invocations)[0][1] is None


def test_existing_scan_cli_retains_available_source_metadata(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from drskill.cli import app
    monkeypatch.setenv("DRSKILL_HOME", str(tmp_path))
    path = session(tmp_path, "win.jsonl", [result()], cwd="C:/work",
                   os="win32", runtimeVersion="sanitized-runtime", version=3)
    output = CliRunner().invoke(app, ["audit", "--global", "--harness", "pi", "--json"])
    assert output.exit_code == 0, output.output
    payload = json.loads(output.output)
    source = payload["sources"][str(path)]
    assert source["path_namespace"] == "windows"
    assert source["producer_version"] == "sanitized-runtime"
    assert source["session_format_version"] == 3
    assert source["inspected_records"] == 2


def test_inspected_records_do_not_count_blank_or_malformed_lines(tmp_path):
    path = session(tmp_path, "main.jsonl", [result()])
    path.write_text(path.read_text() + "\nnot-json\n")
    data = pipeline.run_audit_files(tmp_path, [path], "pi", START, END)
    assert data.sources[str(path)]["inspected_records"] == 2
    assert any(d.code == "malformed-json" for d in data.nested_diagnostics)
