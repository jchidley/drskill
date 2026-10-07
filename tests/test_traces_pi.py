import json

from drskill.traces import pi


def _write(tmp_path, events, slug="--proj-x--", name="2026-07-11T18-03-13-846Z_p1.jsonl"):
    d = tmp_path / ".pi" / "agent" / "sessions" / slug
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    previous = None
    for index, event in enumerate(events):
        if event.get("type") == "message" and event.get("id") == "m":
            event["id"] = f"m{index}"
            event["parentId"] = previous
        if event.get("type") != "session":
            previous = event.get("id")
    f.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return f


def _dump(tmp_path, events, name="session.jsonl"):
    """Write events verbatim; caller owns explicit unique ids and parent links."""
    f = tmp_path / name
    f.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return f


def _header(cwd="/proj/x"):
    return {"type": "session", "version": 3, "id": "p1",
            "timestamp": "2026-07-11T18:03:13.846Z", "cwd": cwd}


def _msg(role, content, ts="2026-07-11T18:04:00.000Z"):
    return {"type": "message", "id": "m", "parentId": None, "timestamp": ts,
            "message": {"role": role, "content": content}}


def _success(call_id):
    result = _msg("toolResult", [{"type": "text", "text": "skill contents"}])
    result["message"].update(toolCallId=call_id, toolName="read", isError=False)
    return result


def _read(path, call_id="read_0"):
    return {"type": "toolCall", "id": call_id, "name": "read",
            "arguments": {"path": path}}


def test_discover(tmp_path):
    f = _write(tmp_path, [_header()])
    assert pi.discover(tmp_path) == [f]


def test_read_of_skill_md_is_heuristic_skill_with_reasoning(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", [{"type": "text", "text": "use the maps skill"}]),
        _msg("assistant", [
            {"type": "thinking", "thinking": "Load overturemaps first."},
            _read("/Users/d/.pi/agent/skills/overturemaps/SKILL.md"),
        ]),
        _success("read_0"),
    ])
    [inv] = pi.extract(f).invocations
    assert (inv.kind, inv.name, inv.detection) == ("skill", "overturemaps", "skill-read")
    assert inv.evidence_kind == "skill-file-read"
    assert inv.query == "use the maps skill"
    assert inv.reasoning == "Load overturemaps first."
    assert inv.project == "/proj/x"
    assert inv.session_id == "p1"


def test_skill_read_records_source_line(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", [{"type": "text", "text": "use the maps skill"}]),
        _msg("assistant", [
            {"type": "thinking", "thinking": "Load overturemaps first."},
            _read("/Users/d/.pi/agent/skills/overturemaps/SKILL.md"),
        ]),
        _success("read_0"),
    ])
    [inv] = pi.extract(f).invocations
    assert inv.source_line == 3  # 1-based: line 3 holds the assistant message
    assert inv.result_source_line == 4  # the certifying successful result


def test_read_evidence_fields_record_identity_and_certifying_result(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", [{"type": "text", "text": "use the maps skill"}]),
        _msg("assistant", [
            {"type": "thinking", "thinking": "Load maps."},
            {"type": "toolCall", "id": "read_0", "name": "read",
             "arguments": {"path": "/x/skills/maps/SKILL.md", "limit": 50}},
        ]),
        _success("read_0"),
    ])
    [inv] = pi.extract(f).invocations
    assert inv.evidence_kind == "skill-file-read"
    assert inv.entry_id == "m2"
    assert inv.parent_id == "m1"
    assert inv.turn_id == "m1"
    assert inv.requested_path == "/x/skills/maps/SKILL.md"
    assert inv.resolved_path == "/x/skills/maps/SKILL.md"
    assert inv.result_entry_id == "m3"
    assert inv.result_source_line == 4
    assert inv.combined_use_id is None
    assert any("Partial read" in q for q in inv.qualifications)


def test_shell_text_mentioning_skill_md_is_not_a_load(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("assistant", [
            {"type": "toolCall", "id": "bash_1", "name": "bash",
             "arguments": {"command": "cat /x/skills/plain-writing/SKILL.md"}},
        ]),
    ])
    assert pi.extract(f).invocations == []


def test_failed_skill_read_is_not_counted_as_a_load(tmp_path):
    failed = _msg("toolResult", [{
        "type": "text", "text": "ENOENT: no such file or directory",
    }])
    failed["message"].update(
        toolCallId="read_0", toolName="read", isError=True,
    )
    f = _write(tmp_path, [
        _header(),
        _msg("user", "what skills do you have?"),
        _msg("assistant", [_read("/missing/skills/git/SKILL.md")]),
        failed,
    ])
    assert pi.extract(f).invocations == []


def test_unfinished_read_is_not_counted(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", "load maps"),
        _msg("assistant", [_read("/x/skills/maps/SKILL.md")]),
    ])
    assert pi.extract(f).invocations == []


def test_read_with_unconfirmed_result_is_not_counted(tmp_path):
    unknown = _msg("toolResult", [{"type": "text", "text": "maybe succeeded"}])
    unknown["message"].update(toolCallId="read_0", toolName="read")
    f = _write(tmp_path, [
        _header(),
        _msg("assistant", [_read("/x/skills/maps/SKILL.md")]),
        unknown,
    ])
    assert pi.extract(f).invocations == []


def test_mcp_style_toolcall_reserved_pattern(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("assistant", [
            {"type": "toolCall", "id": "x_0", "name": "mcp__pencil__get_screenshot",
             "arguments": {}},
        ]),
    ])
    [inv] = pi.extract(f).invocations
    assert (inv.kind, inv.server, inv.name) == ("mcp_tool", "pencil", "get_screenshot")
    assert inv.detection == "explicit"


def test_builtin_tools_ignored_and_toolresults_not_queries(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", [{"type": "text", "text": "the question"}]),
        _msg("toolResult", [{"type": "text", "text": "file contents"}]),
        _msg("assistant", [
            {"type": "toolCall", "id": "bash_9", "name": "bash",
             "arguments": {"command": "ls"}},
            _read("/x/skills/foo/SKILL.md", call_id="read_1"),
        ]),
        _success("read_1"),
    ])
    [inv] = pi.extract(f).invocations
    assert inv.name == "foo"
    assert inv.query == "the question"


def test_string_user_content_and_explicit_skill_command(tmp_path):
    user = _msg("user", "<skill name=\"pdf-tools\" location=\"/x/SKILL.md\">body</skill>")
    f = _write(tmp_path, [_header(), user])
    [inv] = pi.extract(f).invocations
    assert (inv.name, inv.detection) == ("pdf-tools", "command-marker")
    assert inv.evidence_kind == "instruction-delivery"
    assert inv.requested_path == "/x/SKILL.md"
    assert inv.resolved_path == "/x/SKILL.md"
    assert inv.query == "/skill:pdf-tools"


def test_quoted_skill_block_is_not_a_command(tmp_path):
    f = _write(tmp_path, [_header(), _msg(
        "user", 'Can you explain <skill name="maps">body</skill>?'
    )])
    assert pi.extract(f).invocations == []


def test_command_and_same_turn_skill_read_share_one_combined_use(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps" location="/x/skills/maps/SKILL.md">body</skill> query'),
        _msg("assistant", [_read("/x/skills/maps/SKILL.md")]),
        _success("read_0"),
    ])
    command, read = pi.extract(f).invocations
    assert (command.detection, command.evidence_kind) == ("command-marker", "instruction-delivery")
    assert (read.detection, read.evidence_kind) == ("skill-read", "skill-file-read")
    assert command.combined_use_id is not None
    assert command.combined_use_id == read.combined_use_id
    assert command.resolved_path == read.resolved_path == "/x/skills/maps/SKILL.md"
    assert command.query == "/skill:maps query"


def test_next_turn_read_after_command_counts_separately(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps" location="/x/skills/maps/SKILL.md">body</skill>'),
        _msg("user", "Load maps again"),
        _msg("assistant", [_read("/x/skills/maps/SKILL.md")]),
        _success("read_0"),
    ])
    command, read = pi.extract(f).invocations
    assert [command.detection, read.detection] == ["command-marker", "skill-read"]
    assert command.combined_use_id is None
    assert read.combined_use_id is None


def test_same_turn_different_read_path_is_not_combined(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps" location="/a/skills/maps/SKILL.md">body</skill>'),
        _msg("assistant", [_read("/b/skills/maps/SKILL.md")]),
        _success("read_0"),
    ])
    command, read = pi.extract(f).invocations
    assert command.combined_use_id is None
    assert read.combined_use_id is None
    assert (command.resolved_path, read.resolved_path) == (
        "/a/skills/maps/SKILL.md", "/b/skills/maps/SKILL.md")


def test_empty_followup_turn_does_not_reuse_command(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps">body</skill>'),
        _msg("user", ""),
        _msg("assistant", [_read("/x/skills/maps/SKILL.md")]),
        _success("read_0"),
    ])
    command, read = pi.extract(f).invocations
    assert command.detection == "command-marker"
    assert (read.detection, read.query) == ("skill-read", None)


def test_branch_queries_and_reasoning_follow_parent_links(tmp_path):
    first = _msg("user", "first branch")
    first["id"] = "u1"
    old_assistant = _msg("assistant", [
        {"type": "thinking", "thinking": "old branch reasoning"},
        _read("/x/skills/old/SKILL.md", call_id="r1"),
    ])
    old_assistant.update(id="a1", parentId="u1")
    old_result = _success("r1")
    old_result.update(id="r1res", parentId="a1")
    branch = _msg("user", "new branch")
    branch.update(id="u2", parentId=None)
    new_assistant = _msg("assistant", [
        _read("/x/skills/new/SKILL.md", call_id="r2"),
    ])
    new_assistant.update(id="a2", parentId="u2")
    new_result = _success("r2")
    new_result.update(id="r2res", parentId="a2")
    f = _write(tmp_path, [
        _header(), first, old_assistant, old_result, branch, new_assistant, new_result,
    ])
    old, new = pi.extract(f).invocations
    assert (old.query, old.reasoning) == ("first branch", "old branch reasoning")
    assert (new.query, new.reasoning) == ("new branch", None)


def test_result_in_other_branch_does_not_certify_read(tmp_path):
    user1 = _msg("user", "branch one")
    user1["id"] = "u1"
    a1 = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    a1.update(id="a1", parentId="u1")
    user2 = _msg("user", "branch two")
    user2.update(id="u2", parentId=None)
    a2 = _msg("assistant", [])
    a2.update(id="a2", parentId="u2")
    result = _success("read_0")
    result.update(id="r1", parentId="a2")
    f = _dump(tmp_path, [_header(), user1, a1, user2, a2, result])
    assert pi.extract(f).invocations == []


def test_duplicate_entry_ids_reject_read_certification(tmp_path):
    user = _msg("user", "use maps")
    user["id"] = "u1"
    assistant = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    assistant.update(id="dup", parentId="u1")
    result = _success("read_0")
    result.update(id="dup", parentId="dup")
    f = _dump(tmp_path, [_header(), user, assistant, result])
    assert pi.extract(f).invocations == []


def test_contradictory_results_reject_read(tmp_path):
    user = _msg("user", "use maps")
    user["id"] = "u1"
    assistant = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    assistant.update(id="a1", parentId="u1")
    ok = _success("read_0")
    ok.update(id="r1", parentId="a1")
    bad = _msg("toolResult", [{"type": "text", "text": "boom"}])
    bad["message"].update(toolCallId="read_0", toolName="read", isError=True)
    bad.update(id="r2", parentId="a1")
    f = _dump(tmp_path, [_header(), user, assistant, ok, bad])
    assert pi.extract(f).invocations == []


def test_duplicate_successful_results_reject_read(tmp_path):
    user = _msg("user", "use maps")
    user["id"] = "u1"
    assistant = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    assistant.update(id="a1", parentId="u1")
    ok1 = _success("read_0")
    ok1.update(id="r1", parentId="a1")
    ok2 = _success("read_0")
    ok2.update(id="r2", parentId="a1")
    f = _dump(tmp_path, [_header(), user, assistant, ok1, ok2])
    assert pi.extract(f).invocations == []


def test_result_with_wrong_tool_name_does_not_certify(tmp_path):
    user = _msg("user", "use maps")
    user["id"] = "u1"
    assistant = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    assistant.update(id="a1", parentId="u1")
    result = _success("read_0")
    result["message"]["toolName"] = "bash"
    result.update(id="r1", parentId="a1")
    f = _dump(tmp_path, [_header(), user, assistant, result])
    assert pi.extract(f).invocations == []


def test_duplicate_read_call_id_rejects_certification(tmp_path):
    user = _msg("user", "use maps")
    user["id"] = "u1"
    a1 = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    a1.update(id="a1", parentId="u1")
    a2 = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    a2.update(id="a2", parentId="u1")
    result = _success("read_0")
    result.update(id="r1", parentId="a1")
    f = _dump(tmp_path, [_header(), user, a1, a2, result])
    assert pi.extract(f).invocations == []


def test_wrapper_declares_supporting_paths(tmp_path):
    body = (
        "## References\n"
        "References are relative to /x/skills/maps/\n\n"
        "- [guide](guide.md)\n"
        "- [extras](extras/EXTRA.md)\n"
        "- [home](/abs/home.md)\n"
        "- [site](https://example.com/guide)\n"
    )
    user = _msg(
        "user",
        f'<skill name="maps" location="/x/skills/maps/SKILL.md">{body}</skill>',
    )
    f = _write(tmp_path, [_header(), user])
    [command] = pi.extract(f).invocations
    assert command.declared_supporting_paths == [
        "/x/skills/maps/guide.md",
        "/x/skills/maps/extras/EXTRA.md",
        "/abs/home.md",
    ]


def test_relative_links_without_declared_base_are_not_guessed(tmp_path):
    user = _msg("user", '<skill name="maps">[guide](guide.md)</skill>')
    f = _write(tmp_path, [_header(), user])
    [command] = pi.extract(f).invocations
    assert command.declared_supporting_paths == []


def test_absolute_markdown_link_is_declared_without_base(tmp_path):
    user = _msg("user", '<skill name="maps">[home](/abs/home.md)</skill>')
    f = _write(tmp_path, [_header(), user])
    [command] = pi.extract(f).invocations
    assert command.declared_supporting_paths == ["/abs/home.md"]


def test_wrapper_relative_location_resolves_against_cwd(tmp_path):
    f = _write(tmp_path, [
        _header(cwd="/proj/x"),
        _msg("user", '<skill name="maps" location="skills/maps/SKILL.md">body</skill>'),
    ])
    [command] = pi.extract(f).invocations
    assert command.requested_path == "skills/maps/SKILL.md"
    assert command.resolved_path == "/proj/x/skills/maps/SKILL.md"


def test_custom_session_directory_from_environment(tmp_path, monkeypatch):
    custom = tmp_path / "custom-sessions"
    custom.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(custom))
    assert pi.trace_root(tmp_path) == custom


def test_custom_agent_directory_from_environment(tmp_path, monkeypatch):
    agent = tmp_path / "custom-agent"
    monkeypatch.delenv("PI_CODING_AGENT_SESSION_DIR", raising=False)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    assert pi.trace_root(tmp_path) == agent / "sessions"

def test_duplicate_result_entry_id_rejects_certification(tmp_path):
    user = _msg("user", "use maps")
    user["id"] = "u1"
    assistant = _msg("assistant", [_read("/x/skills/maps/SKILL.md")])
    assistant.update(id="a1", parentId="u1")
    result = _success("read_0")
    result.update(id="dup", parentId="a1")
    other = _msg("user", "later turn")
    other.update(id="dup", parentId="u1")
    f = _dump(tmp_path, [_header(), user, assistant, result, other])
    assert pi.extract(f).invocations == []

def test_command_and_same_turn_read_both_survive_without_location(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps">body</skill> query'),
        _msg("assistant", [_read("/x/skills/maps/SKILL.md")]),
        _success("read_0"),
    ])
    command, read = pi.extract(f).invocations
    assert command.detection == "command-marker"
    assert read.detection == "skill-read"
    assert command.combined_use_id is None
    assert read.combined_use_id is None
