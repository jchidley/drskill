"""The audit unit of analysis: one skill or MCP tool invocation seen in a trace."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class Invocation(BaseModel):
    harness: str  # claude-code | codex | pi | copilot
    session_id: str
    project: str | None = None  # cwd from trace metadata, None if unknowable
    timestamp: dt.datetime
    kind: Literal["skill", "mcp_tool"]
    name: str
    server: str | None = None  # MCP server, only when kind == "mcp_tool"
    query: str | None = None  # excerpt of the user message that opened the turn
    reasoning: str | None = None  # excerpt of the nearest preceding thinking text
    sidechain: bool = False
    detection: Literal["explicit", "skill-read", "command-marker"]
    source_file: str  # the trace file, evidence for drill-downs
    source_line: int | None = None  # 1-based JSONL line of the producing event

    # Pi native evidence hardening (ticket 03). Optional so other harnesses keep
    # their current shape; None means "not classified for this evidence axis".
    evidence_kind: (
        Literal["instruction-delivery", "skill-file-read", "supporting-read"] | None
    ) = None
    entry_id: str | None = None  # id of the message entry that produced this row
    parent_id: str | None = None  # parentId link of that entry
    turn_id: str | None = None  # nearest ancestor user message entry id
    requested_path: str | None = None  # original read path / wrapper location
    resolved_path: str | None = None  # lexical recorded POSIX/Windows namespace, not realpath
    result_entry_id: str | None = None  # id of the certifying successful result
    result_source_line: int | None = None  # 1-based line of that result entry
    combined_use_id: str | None = None  # ties a wrapper and its same-turn read
    qualifications: list[str] = Field(default_factory=list)
    evidence_owner: tuple[str, str, str] | None = None
    inheritance: Literal["unresolved", "independent", "inherited"] | None = None
    declared_supporting_paths: list[str] = Field(default_factory=list)


class ExtractResult(BaseModel):
    invocations: list[Invocation] = Field(default_factory=list)
    recognized: int = 0  # count of events the adapter understood; 0 flags format drift
