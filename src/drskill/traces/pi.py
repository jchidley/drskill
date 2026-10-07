"""Trace adapter for Pi agent sessions.

Reads Pi's JSONL session trees. Skills surface either as successful native
``read`` calls on SKILL.md paths or as expanded ``/skill:name`` user messages. Query
and reasoning attribution follows parent links, so switching branches does not
leak context from the previously active branch.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from drskill.traces.common import excerpt, parse_ts, skill_md_names
from drskill.traces.model import ExtractResult, Invocation

HARNESS = "pi"
VERSION = 8

_SKILL_BLOCK = re.compile(r'^\s*<skill\s+name=["\']([^"\']+)["\'](?:\s|>)')


def trace_root(home: Path) -> Path:
    """Return Pi's effective session root, including its documented overrides."""
    session_dir = os.environ.get("PI_CODING_AGENT_SESSION_DIR")
    if session_dir:
        return Path(session_dir).expanduser()
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR")
    if agent_dir:
        return Path(agent_dir).expanduser() / "sessions"
    return home / ".pi" / "agent" / "sessions"


def discover(home: Path) -> list[Path]:
    root = trace_root(home)
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*.jsonl"))


def _text(content: object) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    texts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return texts[0] if texts else None


def _query(content: object) -> str | None:
    text = _text(content)
    if not text:
        return None
    match = _SKILL_BLOCK.match(text)
    if match:
        closing = text.find("</skill>", match.end())
        args = text[closing + len("</skill>"):].strip() if closing >= 0 else ""
        return f"/skill:{match.group(1)}" + (f" {args}" if args else "")
    return text


def _thinking(content: object) -> str | None:
    if not isinstance(content, list):
        return None
    latest = None
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            text = block.get("thinking") or ""
            if text.strip():
                latest = text
    return latest


def extract(path: Path) -> ExtractResult:
    out: list[Invocation] = []
    recognized = 0
    session_id = path.stem
    project: str | None = None
    records: list[tuple[dict, int, str, str | None]] = []
    by_id: dict[str, tuple[dict, int, str, str | None]] = {}
    successful_tool_calls: set[str] = set()
    previous_id: str | None = None

    for lineno, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "session":
            recognized += 1
            session_id = str(event.get("id", session_id))
            if isinstance(event.get("cwd"), str):
                project = event["cwd"]
            continue

        # Every non-header entry can be an ancestor in Pi's session tree.
        entry_id = str(event.get("id") or f"line-{lineno}")
        raw_parent = event.get("parentId")
        parent_id = str(raw_parent) if raw_parent is not None else None
        # Version 1 sessions were linear and may not carry parent links.
        if "parentId" not in event:
            parent_id = previous_id
        record = (event, lineno, entry_id, parent_id)
        records.append(record)
        by_id[entry_id] = record
        previous_id = entry_id

        if event.get("type") != "message":
            continue
        message = event.get("message") or {}
        if message.get("role") == "toolResult" and message.get("isError") is False:
            tool_call_id = message.get("toolCallId")
            if isinstance(tool_call_id, str):
                successful_tool_calls.add(tool_call_id)
        if message.get("role") in ("user", "assistant"):
            content = message.get("content")
            if isinstance(content, str) or isinstance(content, list):
                recognized += 1

    def ancestors(parent_id: str | None):
        seen: set[str] = set()
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            record = by_id.get(parent_id)
            if record is None:
                break
            yield record[0]
            parent_id = record[3]

    # A command and its subsequent read are one use in the same user turn.
    # Index commands first so branching or record order cannot affect deduplication.
    explicit_by_user: dict[str, str] = {}
    for event, _lineno, entry_id, _parent_id in records:
        if event.get("type") != "message":
            continue
        message = event.get("message") or {}
        if message.get("role") != "user":
            continue
        text = _text(message.get("content"))
        match = _SKILL_BLOCK.match(text) if text else None
        if match:
            explicit_by_user[entry_id] = match.group(1)

    for event, lineno, _entry_id, parent_id in records:
        if event.get("type") != "message":
            continue
        message = event.get("message") or {}
        role = message.get("role")
        content = message.get("content")
        ts = parse_ts(event.get("timestamp"))
        if role not in ("user", "assistant") or ts is None:
            continue
        base = dict(
            harness=HARNESS,
            session_id=session_id,
            project=project,
            timestamp=ts,
            sidechain=False,
            source_file=str(path),
            source_line=lineno,
        )
        if role == "user":
            text = _text(content)
            match = _SKILL_BLOCK.match(text) if text else None
            if match:
                out.append(Invocation(
                    **base,
                    kind="skill",
                    name=match.group(1),
                    query=_query(content),
                    detection="command-marker",
                ))
            continue

        query = None
        user_id = None
        saw_user = False
        prior_thinking = None
        for ancestor in ancestors(parent_id):
            ancestor_message = ancestor.get("message") or {}
            ancestor_role = ancestor_message.get("role")
            if not saw_user and ancestor_role == "user":
                saw_user = True
                query = _query(ancestor_message.get("content"))
                user_id = ancestor.get("id")
            if prior_thinking is None and ancestor_role == "assistant":
                prior_thinking = _thinking(ancestor_message.get("content"))
            if saw_user and prior_thinking is not None:
                break

        current_thinking = prior_thinking
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "thinking":
                text = block.get("thinking") or ""
                if text.strip():
                    current_thinking = text
                continue
            if block.get("type") != "toolCall":
                continue
            name = block.get("name", "")
            args = block.get("arguments") or {}
            tool_call_id = block.get("id")
            if name.startswith("mcp__"):
                parts = name.split("__")
                if len(parts) >= 3:
                    out.append(Invocation(
                        **base,
                        kind="mcp_tool",
                        server=parts[1],
                        name="__".join(parts[2:]),
                        query=query,
                        reasoning=excerpt(current_thinking),
                        detection="explicit",
                    ))
                continue
            if name == "read" and isinstance(args, dict):
                if not isinstance(tool_call_id, str) or tool_call_id not in successful_tool_calls:
                    continue
                evidence = str(args.get("path", ""))
                for skill in skill_md_names(evidence):
                    if user_id is not None and explicit_by_user.get(user_id) == skill:
                        continue
                    out.append(Invocation(
                        **base,
                        kind="skill",
                        name=skill,
                        query=query,
                        reasoning=excerpt(current_thinking),
                        detection="skill-read",
                    ))
    return ExtractResult(invocations=out, recognized=recognized)
