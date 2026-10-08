"""Qualified finalized nested-read evidence; never parses script or display text."""
from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from drskill.traces.model import ExtractResult
from drskill.traces.common import parse_ts, resolve_read_path

RECORDER_BOUNDS = "recorder bounds: 256 calls, 8 KiB arguments/call, 32 KiB arguments/result"


class NestedDiagnostic(BaseModel):
    code: str
    source_file: str
    source_line: int | None = None
    detail: str


class NestedRead(BaseModel):
    project: str | None = None
    turn_id: str | None = None
    evidence_kind: str | None = None
    skill_name: str | None = None
    combined_use_id: str | None = None
    occurrence: tuple[str, str, str]
    result_record_time: str | None
    result_parent_id: str | None = None
    requested_path: str
    resolved_path: str | None
    source_file: str
    source_line: int
    source_sha256: str
    provenance: dict = Field(default_factory=dict)
    qualifications: list[str] = Field(default_factory=list)
    inheritance: Literal["unresolved", "independent", "inherited"] = "unresolved"
    execution_owner: tuple[str, str, str] | None = None
    window_membership: Literal["inside", "unknown"] = "unknown"


class PiExtractResult(ExtractResult):
    session_header: dict = Field(default_factory=dict)
    source_sha256: str | None = None
    inspected_records: int = 0
    result_payload_hashes: dict[str, str] = Field(default_factory=dict)
    entry_parents: dict[str, str | None] = Field(default_factory=dict)
    nested_reads: list[NestedRead] = Field(default_factory=list)
    nested_diagnostics: list[NestedDiagnostic] = Field(default_factory=list)


def extract_nested(path: Path, raw: bytes) -> PiExtractResult:
    return _extract_snapshot(path, raw)


def _extract_snapshot(path: Path, raw: bytes) -> PiExtractResult:
    result = PiExtractResult()
    records = []
    source_sha256 = hashlib.sha256(raw).hexdigest()
    result.source_sha256 = source_sha256

    def diagnostic(code, line, detail):
        result.nested_diagnostics.append(NestedDiagnostic(
            code=code, source_file=str(path), source_line=line, detail=detail))
    for line, text in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
        try:
            event = json.loads(text)
        except ValueError:
            diagnostic("malformed-json", line, "Record unavailable")
            continue
        if isinstance(event, dict):
            records.append((line, event))
        else:
            diagnostic("malformed-entry", line, "Expected object")
    result.inspected_records = len(records)
    headers = [event for _, event in records if event.get("type") == "session"]
    header = headers[0] if len(headers) == 1 else {}
    result.session_header = header
    session_id = header.get("id")
    cwd = header.get("cwd")
    seen_evidence = False
    seen_entries = set()
    duplicate_entries = set()
    for _, event in records:
        entry_id = event.get("id")
        if isinstance(entry_id, str):
            if entry_id in seen_entries:
                duplicate_entries.add(entry_id)
            seen_entries.add(entry_id)
    parents = {e.get("id"): e for _, e in records if isinstance(e.get("id"), str)
               and e.get("id") not in duplicate_entries}
    for line, event in records:
        message = event.get("message")
        if event.get("type") != "message" or not isinstance(message, dict):
            continue
        if message.get("role") != "toolResult" or message.get("toolName") != "codemode":
            continue
        nested = message.get("nestedCalls")
        if nested is None:
            diagnostic("missing-structured-evidence", line,
                       "Missing field does not prove no nested use or runtime capability")
            continue
        seen_evidence = True
        if not isinstance(nested, dict) or not isinstance(nested.get("calls"), list):
            diagnostic("malformed-nested-record", line, "Expected structured calls array")
            continue
        if nested.get("complete") is not True:
            diagnostic("incomplete-coverage", line, RECORDER_BOUNDS)
        calls = nested["calls"]
        ids = [row.get("id") for row in calls if isinstance(row, dict) and isinstance(row.get("id"), str)]
        for row in calls:
            if not isinstance(row, dict):
                diagnostic("malformed-call", line, "Expected object")
                continue
            if row.get("name") != "read":
                continue
            call_id = row.get("id")
            args = row.get("arguments")
            requested = args.get("path") if isinstance(args, dict) else None
            if row.get("status") != "ok":
                diagnostic("read-" + str(row.get("status", "unknown")), line,
                           "No successful read outcome")
                continue
            if (not isinstance(session_id, str) or not session_id.strip()
                or not isinstance(event.get("id"), str) or not event["id"].strip()
                or event["id"] in duplicate_entries
                or not isinstance(call_id, str) or not call_id.strip()
                or ids.count(call_id) != 1
                or not isinstance(requested, str) or not requested.strip()):
                diagnostic("invalid-read-evidence", line,
                           "Stable session/result/call identity and structured path required; " + RECORDER_BOUNDS)
                continue
            qualifications = [
                "Finalized pipeline outcome for recorded request, not attested OS access; transformations may change effective path/outcome",
                "Lexical path only; historical resource identity, symlink target and workflow completion unproven",
                "Result-record time is not nested-call start time",
                "Full-file coverage unproven",
            ]
            resolved, path_qualifications = resolve_read_path(requested, cwd)
            qualifications.extend(path_qualifications)
            if "offset" in args or "limit" in args:
                qualifications.append("Partial read requested via offset/limit")
            time = event.get("timestamp")
            if parse_ts(time) is None:
                time = None
                diagnostic("missing-result-time", line, "No retained result-record timestamp")
            ancestor_id = event.get("parentId")
            visited = set()
            turn_id = None
            while isinstance(ancestor_id, str) and ancestor_id not in visited:
                visited.add(ancestor_id)
                ancestor = parents.get(ancestor_id)
                if ancestor is None:
                    break
                if isinstance(ancestor.get("message"), dict) and ancestor["message"].get("role") == "user":
                    turn_id = ancestor_id
                    break
                ancestor_id = ancestor.get("parentId")
            result.nested_reads.append(NestedRead(
                project=cwd if isinstance(cwd, str) else None, turn_id=turn_id,
                occurrence=(session_id, event["id"], call_id),
                result_record_time=time,
                result_parent_id=event.get("parentId") if isinstance(event.get("parentId"), str) else None,
                requested_path=requested, resolved_path=resolved,
                source_file=str(path), source_line=line,
                source_sha256=source_sha256,
                provenance=event.get("evidenceSource") if isinstance(event.get("evidenceSource"), dict) else {},
                qualifications=qualifications))
    if not seen_evidence:
        diagnostic("capability-unknown", None,
                   "No structured records retained; format version cannot establish recording capability")
    entries = {event["id"]: event for _, event in records if isinstance(event.get("id"), str)}
    result.entry_parents = {
        key: event.get("parentId") if isinstance(event.get("parentId"), str) else None
        for key, event in entries.items() if key not in duplicate_entries
        and "parentId" in event
        and (event["parentId"] is None or isinstance(event["parentId"], str))
    }
    result.result_payload_hashes = {
        key: hashlib.sha256(json.dumps(event.get("message"), sort_keys=True,
                                      ensure_ascii=True).encode()).hexdigest()
        for key, event in entries.items()
    }
    return result


def extract_corpus(paths: list[Path]) -> PiExtractResult:
    """Inspect explicitly supplied physical logs, including all raw branches.

    Never opens unrequested parent/child logs. Parent paths are provenance links,
    not permission to traverse the filesystem or infer missing child executions.
    """
    result = PiExtractResult()
    snapshots: dict[Path, PiExtractResult] = {}
    for path in sorted(set(p.resolve() for p in paths)):
        try:
            raw = path.read_bytes()
            snapshot = _extract_snapshot(path, raw)
        except OSError as error:
            result.nested_diagnostics.append(NestedDiagnostic(
                code="missing-session", source_file=str(path), detail=type(error).__name__))
            continue
        snapshots[path] = snapshot
        result.nested_diagnostics.extend(snapshot.nested_diagnostics)

    return reconcile_corpus({str(path): snapshot for path, snapshot in snapshots.items()},
                            result.nested_diagnostics)


def reconcile_corpus(extracted: dict[str, PiExtractResult],
                     diagnostics: list[NestedDiagnostic] | None = None,
                     source_locations: dict[str, str] | None = None) -> PiExtractResult:
    """Recompute ownership from supplied snapshots, including cached snapshots.

    Payload hashes cover the entire retained result message; no raw file bodies
    are persisted in the cache to establish payload equality.
    """
    snapshots = {Path(path).resolve(): value.model_copy(deep=True)
                 for path, value in extracted.items()}
    result = PiExtractResult()
    for snapshot in snapshots.values():
        result.nested_reads.extend(snapshot.nested_reads)
    result.nested_diagnostics = (list(diagnostics) if diagnostics is not None else
                                [d for s in snapshots.values() for d in s.nested_diagnostics])
    session_ids = [snapshot.session_header.get("id") for snapshot in snapshots.values()]
    locations = {Path(p).resolve(): value for p, value in (source_locations or {}).items()}
    source_index: dict[str, list[Path]] = {}
    for path in snapshots:
        # Physical provenance is always available; recorded locations are supplied
        # declarations, never inferred from session IDs or resource paths.
        for value in (str(path), locations.get(path)):
            if value is None:
                continue
            normalized, _ = resolve_read_path(value, None)
            if normalized is None:
                raise ValueError("Source location must be an absolute lexical POSIX or Windows path")
            candidates = source_index.setdefault(normalized, [])
            if path not in candidates:
                candidates.append(path)

    def ancestry(path):
        chain = []
        seen = {path}
        while True:
            header = snapshots[path].session_header
            session_id = header.get("id")
            if not isinstance(session_id, str) or session_ids.count(session_id) != 1:
                return chain, "ambiguous-session"
            parent = header.get("parentSession")
            if parent is None:
                return chain, None
            if not isinstance(parent, str) or not parent.strip():
                return chain, "invalid-parent"
            recorded = locations.get(path, str(path))
            normalized_location, _ = resolve_read_path(recorded, None)
            parent_location, _ = resolve_read_path(parent, posixpath.dirname(normalized_location))
            candidates = source_index.get(parent_location, [])
            if len(candidates) != 1:
                return chain, "ambiguous-parent" if candidates else "missing-parent"
            parent_path = candidates[0]
            if parent_path in seen:
                return chain, "cycle"
            seen.add(parent_path)
            chain.append(parent_path)
            path = parent_path

    def verified_owner(path, entry_ids, matches):
        chain, problem = ancestry(path)
        owner = None
        if problem is None:
            for ancestor in chain:
                candidate = snapshots[ancestor].result_payload_hashes
                if not any(entry_id in candidate for entry_id in entry_ids):
                    continue
                if any(candidate.get(entry_id) != snapshots[path].result_payload_hashes.get(entry_id)
                       for entry_id in entry_ids):
                    return None, "conflicting-payload"
                found = matches(snapshots[ancestor])
                if len(found) != 1:
                    return None, "invalid-ancestor-evidence"
                owner = found[0]
        return owner, problem

    for row in result.nested_reads:
        row.inheritance = "unresolved"
        row.execution_owner = None
        path = Path(row.source_file).resolve()
        owner, problem = verified_owner(
            path, [row.occurrence[1]],
            lambda snapshot: [r for r in snapshot.nested_reads
                              if r.occurrence[1:] == row.occurrence[1:]])
        if problem:
            result.nested_diagnostics.append(NestedDiagnostic(
                code="ancestry-" + problem, source_file=row.source_file,
                source_line=row.source_line,
                detail="Execution ownership unresolved; do not infer a distinct execution"))
            continue
        owner = owner or row
        row.execution_owner = owner.occurrence
        row.inheritance = "independent" if owner is row else "inherited"
        if owner is not row:
            row.resolved_path = owner.resolved_path
            row.qualifications = list(owner.qualifications)
            row.qualifications.append("Inherited request path uses verified execution owner's context")

    for path, snapshot in snapshots.items():
        for inv in snapshot.invocations:
            result.invocations.append(inv)
            if inv.evidence_kind is None:
                continue
            inv.inheritance = "unresolved"
            inv.evidence_owner = None
            entry_ids = [inv.entry_id]
            if inv.result_entry_id:
                entry_ids.append(inv.result_entry_id)
            owner, problem = verified_owner(
                path, entry_ids,
                lambda ancestor: [i for i in ancestor.invocations
                                  if i.entry_id == inv.entry_id
                                  and i.result_entry_id == inv.result_entry_id
                                  and i.evidence_kind == inv.evidence_kind])
            if problem:
                result.nested_diagnostics.append(NestedDiagnostic(
                    code="ancestry-" + problem, source_file=inv.source_file,
                    source_line=inv.source_line,
                    detail="Native/delivery observation ownership unresolved"))
                inv.combined_use_id = None
                continue
            owner = owner or inv
            inv.evidence_owner = (owner.session_id, owner.entry_id,
                                  owner.result_entry_id or "delivery")
            inv.inheritance = "independent" if owner is inv else "inherited"
            if owner is not inv:
                inv.resolved_path = owner.resolved_path
                inv.declared_supporting_paths = list(owner.declared_supporting_paths)
                inv.qualifications = list(owner.qualifications)
                inv.qualifications.append("Inherited evidence uses verified owner's context")
                inv.combined_use_id = owner.combined_use_id
    return result
