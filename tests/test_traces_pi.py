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


def test_discover(tmp_path):
    f = _write(tmp_path, [_header()])
    assert pi.discover(tmp_path) == [f]


def test_read_of_skill_md_is_heuristic_skill_with_reasoning(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", [{"type": "text", "text": "use the maps skill"}]),
        _msg("assistant", [
            {"type": "thinking", "thinking": "Load overturemaps first."},
            {"type": "toolCall", "id": "read_0", "name": "read",
             "arguments": {"path": "/Users/d/.pi/agent/skills/overturemaps/SKILL.md"}},
        ]),
        _success("read_0"),
    ])
    [inv] = pi.extract(f).invocations
    assert (inv.kind, inv.name, inv.detection) == ("skill", "overturemaps", "skill-read")
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
            {"type": "toolCall", "id": "read_0", "name": "read",
             "arguments": {"path": "/Users/d/.pi/agent/skills/overturemaps/SKILL.md"}},
        ]),
        _success("read_0"),
    ])
    [inv] = pi.extract(f).invocations
    assert inv.source_line == 3  # 1-based: line 3 holds the assistant message


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
        _msg("assistant", [{
            "type": "toolCall", "id": "read_0", "name": "read",
            "arguments": {"path": "/missing/skills/git/SKILL.md"},
        }]),
        failed,
    ])
    assert pi.extract(f).invocations == []


def test_unfinished_read_is_not_counted(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", "load maps"),
        _msg("assistant", [{
            "type": "toolCall", "id": "read_0", "name": "read",
            "arguments": {"path": "/x/skills/maps/SKILL.md"},
        }]),
    ])
    assert pi.extract(f).invocations == []


def test_read_with_unconfirmed_result_is_not_counted(tmp_path):
    unknown = _msg("toolResult", [{"type": "text", "text": "maybe succeeded"}])
    unknown["message"].update(toolCallId="read_0", toolName="read")
    f = _write(tmp_path, [
        _header(),
        _msg("assistant", [{
            "type": "toolCall", "id": "read_0", "name": "read",
            "arguments": {"path": "/x/skills/maps/SKILL.md"},
        }]),
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
            {"type": "toolCall", "id": "read_1", "name": "read",
             "arguments": {"path": "/x/skills/foo/SKILL.md"}},
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
    assert inv.query == "/skill:pdf-tools"


def test_quoted_skill_block_is_not_a_command(tmp_path):
    f = _write(tmp_path, [_header(), _msg(
        "user", 'Can you explain <skill name="maps">body</skill>?'
    )])
    assert pi.extract(f).invocations == []


def test_command_and_successful_read_count_once_at_command_line(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps">body</skill> query'),
        _msg("assistant", [{
            "type": "toolCall", "id": "read_0", "name": "read",
            "arguments": {"path": "/x/skills/maps/SKILL.md"},
        }]),
        _success("read_0"),
    ])
    [inv] = pi.extract(f).invocations
    assert (inv.name, inv.detection, inv.source_line) == ("maps", "command-marker", 2)
    assert inv.query == "/skill:maps query"


def test_next_turn_read_after_command_counts_separately(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps">body</skill>'),
        _msg("user", "Load maps again"),
        _msg("assistant", [{
            "type": "toolCall", "id": "read_0", "name": "read",
            "arguments": {"path": "/x/skills/maps/SKILL.md"},
        }]),
        _success("read_0"),
    ])
    assert [inv.detection for inv in pi.extract(f).invocations] == [
        "command-marker", "skill-read"
    ]


def test_empty_followup_turn_does_not_reuse_command(tmp_path):
    f = _write(tmp_path, [
        _header(),
        _msg("user", '<skill name="maps">body</skill>'),
        _msg("user", ""),
        _msg("assistant", [{
            "type": "toolCall", "id": "read_0", "name": "read",
            "arguments": {"path": "/x/skills/maps/SKILL.md"},
        }]),
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
        {"type": "toolCall", "id": "r1", "name": "read",
         "arguments": {"path": "/x/skills/old/SKILL.md"}},
    ])
    old_assistant.update(id="a1", parentId="u1")
    branch = _msg("user", "new branch")
    branch.update(id="u2", parentId=None)
    new_assistant = _msg("assistant", [
        {"type": "toolCall", "id": "r2", "name": "read",
         "arguments": {"path": "/x/skills/new/SKILL.md"}},
    ])
    new_assistant.update(id="a2", parentId="u2")
    f = _write(tmp_path, [
        _header(), first, old_assistant, branch, new_assistant,
        _success("r1"), _success("r2"),
    ])
    old, new = pi.extract(f).invocations
    assert (old.query, old.reasoning) == ("first branch", "old branch reasoning")
    assert (new.query, new.reasoning) == ("new branch", None)


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
