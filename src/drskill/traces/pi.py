"""Trace adapter for Pi agent sessions.

Reads Pi's JSONL session trees. Skills surface either as successful native
``read`` calls on SKILL.md paths or as expanded ``/skill:name`` user messages. Query
and reasoning attribution follows parent links, so switching branches does not
leak context from the previously active branch.

Native read evidence is hardened (ticket 03): a read only counts when a result
with the matching call id is reachable through the same branch's parent chain,
names the read tool, and carries an explicit isError false. Duplicate
entry/call ids and contradictory or unrelated-branch results never certify.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from drskill.traces.common import (
    excerpt, parse_ts, skill_md_names, resolve_read_path, combined_use_id,
)
from drskill.traces.model import Invocation
from drskill.traces.pi_nested import PiExtractResult, NestedDiagnostic, extract_nested

HARNESS = "pi"
VERSION = 13

_SKILL_OPEN = re.compile(r'^\s*<skill\b([^>]*)>')
_ATTR = re.compile(
    r'([A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')'
)
_MD_LINK = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
_REFERENCES_BASE = re.compile(r'(?i)references?\s+are\s+relative\s+to\s+([^\s,;]+)')


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


def _message(event: dict) -> dict:
    message = event.get("message")
    return message if isinstance(message, dict) else {}


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


def _skill_block(text: str) -> dict | None:
    """Leading expanded <skill ...>...</skill> block, or None."""
    opened = _SKILL_OPEN.match(text)
    if not opened:
        return None
    attrs: dict[str, str] = {}
    for attr in _ATTR.finditer(opened.group(1)):
        value = attr.group(2) if attr.group(2) is not None else attr.group(3)
        attrs[attr.group(1)] = value
    name = attrs.get("name")
    if not name:
        return None
    closing = text.find("</skill>", opened.end())
    body = text[opened.end():closing] if closing >= 0 else ""
    return {"name": name, "location": attrs.get("location"), "body": body,
            "closing": closing}


def _query(content: object) -> str | None:
    text = _text(content)
    if not text:
        return None
    block = _skill_block(text)
    if block is not None:
        closing = block["closing"]
        args = text[closing + len("</skill>"):].strip() if closing >= 0 else ""
        return f"/skill:{block['name']}" + (f" {args}" if args else "")
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


def _declared_supporting_paths(body: str) -> list[str]:
    """Declared supporting references only: explicit markdown links.

    Relative links resolve only against an explicit
    "References are relative to /abs/path" declaration; unqualified relative
    links are not guessed. URLs and anchor-only targets are ignored.
    """
    base_match = _REFERENCES_BASE.search(body)
    base = base_match.group(1).rstrip(".") if base_match else None
    paths: list[str] = []
    for target in _MD_LINK.findall(body):
        target = target.strip()
        if not target or target.startswith("#"):
            continue
        if any(ch.isspace() for ch in target):
            continue
        resolved, _ = resolve_read_path(target, base)
        if resolved is not None:
            paths.append(resolved)
    out: list[str] = []
    seen: set[str] = set()
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def extract(path: Path) -> PiExtractResult:
    out: list[Invocation] = []
    recognized = 0
    session_id = path.stem
    project: str | None = None
    records: list[tuple[dict, int, str, str | None]] = []
    by_id: dict[str, tuple[dict, int, str, str | None]] = {}
    seen_entry_ids: set[str] = set()
    duplicate_entry_ids: set[str] = set()
    previous_id: str | None = None

    raw = path.read_bytes()
    for lineno, line in enumerate(
        raw.decode("utf-8", errors="replace").splitlines(), start=1
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
        if entry_id in seen_entry_ids:
            duplicate_entry_ids.add(entry_id)
        seen_entry_ids.add(entry_id)
        record = (event, lineno, entry_id, parent_id)
        records.append(record)
        by_id[entry_id] = record
        previous_id = entry_id

        if event.get("type") == "message":
            message = _message(event)
            if message.get("role") in ("user", "assistant"):
                content = message.get("content")
                if isinstance(content, str) or isinstance(content, list):
                    recognized += 1

    def ancestor_records(parent_id: str | None):
        seen: set[str] = set()
        while parent_id is not None and parent_id not in seen:
            if parent_id in duplicate_entry_ids:
                break
            seen.add(parent_id)
            record = by_id.get(parent_id)
            if record is None:
                break
            yield record
            parent_id = record[3]

    def in_branch(record: tuple[dict, int, str, str | None], ancestor_id: str) -> bool:
        return (ancestor_id not in duplicate_entry_ids
                and any(parent[2] == ancestor_id for parent in ancestor_records(record[3])))

    results_by_call: dict[str, list[tuple[dict, int, str, str | None]]] = {}
    for record in records:
        event = record[0]
        if event.get("type") != "message":
            continue
        message = _message(event)
        if message.get("role") != "toolResult":
            continue
        call_id = message.get("toolCallId")
        if isinstance(call_id, str):
            results_by_call.setdefault(call_id, []).append(record)

    tool_call_ids: set[str] = set()
    duplicate_tool_call_ids: set[str] = set()
    for record in records:
        event = record[0]
        if event.get("type") != "message":
            continue
        message = _message(event)
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not (isinstance(block, dict) and block.get("type") == "toolCall"):
                continue
            call_id = block.get("id")
            if not isinstance(call_id, str):
                continue
            if call_id in tool_call_ids:
                duplicate_tool_call_ids.add(call_id)
            else:
                tool_call_ids.add(call_id)

    def certify(tool_call_id: object, assistant_id: str):
        if (not isinstance(tool_call_id, str) or not tool_call_id
                or tool_call_id in duplicate_tool_call_ids
                or assistant_id in duplicate_entry_ids):
            return None
        results = [
            r for r in results_by_call.get(tool_call_id, [])
            if in_branch(r, assistant_id)
        ]
        if len(results) != 1:
            return None
        result_event, result_lineno, result_entry_id, _ = results[0]
        if result_entry_id in duplicate_entry_ids:
            return None
        result_message = _message(result_event)
        if (result_message.get("toolName") != "read"
                or result_message.get("isError") is not False):
            return None
        return result_entry_id, result_lineno

    pending: list[tuple[int, dict]] = []
    native_diagnostics: list[NestedDiagnostic] = []
    declared_by_turn = {}
    for event, _, entry_id, _ in records:
        if entry_id in duplicate_entry_ids or _message(event).get("role") != "user":
            continue
        text = _text(_message(event).get("content"))
        wrapper = _skill_block(text) if text else None
        if wrapper:
            declared_by_turn[entry_id] = wrapper

    for event, lineno, entry_id, parent_id in records:
        if event.get("type") != "message":
            continue
        message = _message(event)
        role = message.get("role")
        content = message.get("content")
        ts = parse_ts(event.get("timestamp"))
        if role not in ("user", "assistant"):
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
            block = _skill_block(text) if text else None
            if block is None:
                continue
            requested = block["location"]
            if requested:
                resolved, path_quals = resolve_read_path(requested, project)
            else:
                resolved, path_quals = None, []
            quals = [
                "Expanded skill wrapper is delivery evidence, not authenticated UI-command provenance",
            ]
            if requested:
                quals += path_quals
                if resolved is not None:
                    quals.append("Lexical path only; historical resource identity unproven")
            else:
                quals.append("No explicit skill location recorded")
            pending.append((lineno, dict(
                **base,
                kind="skill",
                name=block["name"],
                query=_query(content),
                detection="command-marker",
                evidence_kind="instruction-delivery",
                entry_id=entry_id,
                parent_id=parent_id,
                turn_id=entry_id,
                requested_path=requested,
                resolved_path=resolved,
                declared_supporting_paths=_declared_supporting_paths(block["body"]),
                qualifications=quals,
            )))
            continue

        query = None
        turn_id = None
        saw_user = False
        prior_thinking = None
        for ancestor in ancestor_records(parent_id):
            ancestor_message = _message(ancestor[0])
            ancestor_role = ancestor_message.get("role")
            if not saw_user and ancestor_role == "user":
                saw_user = True
                query = _query(ancestor_message.get("content"))
                turn_id = ancestor[2]
            if prior_thinking is None and ancestor_role == "assistant":
                prior_thinking = _thinking(ancestor_message.get("content"))
            if saw_user and prior_thinking is not None:
                break

        if not isinstance(content, list):
            continue
        current_thinking = prior_thinking
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
            if name.startswith("mcp__") and ts is not None:
                parts = name.split("__")
                if len(parts) >= 3:
                    pending.append((lineno, dict(
                        **base,
                        kind="mcp_tool",
                        server=parts[1],
                        name="__".join(parts[2:]),
                        query=query,
                        reasoning=excerpt(current_thinking),
                        detection="explicit",
                        entry_id=entry_id,
                        parent_id=parent_id,
                        turn_id=turn_id,
                    )))
                continue
            if name == "read" and isinstance(args, dict):
                evidence = str(args.get("path", ""))
                skill_names = skill_md_names(evidence)
                resolved, path_quals = resolve_read_path(evidence, project)
                declared = declared_by_turn.get(turn_id)
                supporting = (declared is not None and resolved is not None and
                              resolved in _declared_supporting_paths(declared["body"]))
                if supporting:
                    skill_names = [declared["name"]]
                if not skill_names:
                    continue
                quals = [
                    "Finalized pipeline outcome for recorded request, not attested OS access; transformations may change effective path/outcome",
                    "Lexical path only; historical resource identity, symlink target and workflow completion unproven",
                    "Full-file coverage unproven",
                ] + path_quals
                if "offset" in args or "limit" in args:
                    quals.append("Partial read requested via offset/limit")
                certified = certify(tool_call_id, entry_id)
                if certified is None:
                    native_diagnostics.append(NestedDiagnostic(
                        code="native-read-unresolved", source_file=str(path),
                        source_line=lineno,
                        detail="Read lacks an unambiguous same-branch explicit successful read result"))
                    continue
                result_entry_id, result_line = certified
                for skill in skill_names:
                    pending.append((lineno, dict(
                        **base,
                        kind="skill",
                        name=skill,
                        query=query,
                        reasoning=excerpt(current_thinking),
                        detection="skill-read",
                        evidence_kind="supporting-read" if supporting else "skill-file-read",
                        entry_id=entry_id,
                        parent_id=parent_id,
                        turn_id=turn_id,
                        requested_path=evidence,
                        resolved_path=resolved,
                        tool_call_id=tool_call_id,
                        result_entry_id=result_entry_id,
                        result_source_line=result_line,
                        result_record_time=(by_id[result_entry_id][0].get("timestamp")
                                            if parse_ts(by_id[result_entry_id][0].get("timestamp")) else None),
                        qualifications=quals,
                    )))

    # Tie a wrapper and a same-turn read of the exact normalized skill path into
    # one combined use, without losing either evidence row.
    wrapper_rows = [row for _, row in pending if row["detection"] == "command-marker"]
    read_rows = [row for _, row in pending if row.get("evidence_kind") == "skill-file-read"]
    for wrapper in wrapper_rows:
        wrapper_path = wrapper["resolved_path"]
        if wrapper_path is None or wrapper["turn_id"] is None:
            continue
        matched = False
        combined = combined_use_id(session_id, wrapper["turn_id"], wrapper_path)
        for read in read_rows:
            if (read["resolved_path"] == wrapper_path
                    and read["turn_id"] == wrapper["turn_id"]):
                read["combined_use_id"] = combined
                matched = True
        if matched:
            wrapper["combined_use_id"] = combined

    pending.sort(key=lambda item: item[0])
    for _, data in pending:
        out.append(Invocation(**data))

    result = extract_nested(path, raw)
    result.nested_diagnostics.extend(native_diagnostics)
    result.invocations = out
    result.recognized = recognized
    return result
