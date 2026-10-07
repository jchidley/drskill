"""Discover trace files, extract through the cache, filter by scope and time."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, Field

from drskill.traces import cache, claude_code, codex, copilot, pi
from drskill.traces.common import munge_path
from drskill.traces.model import Invocation
from drskill.traces.pi_nested import (
    NestedRead, NestedDiagnostic, PiExtractResult, reconcile_corpus,
    extract_corpus as extract_pi_nested_corpus,
)
from drskill.traces.common import parse_ts

ADAPTERS = {
    claude_code.HARNESS: claude_code,
    codex.HARNESS: codex,
    pi.HARNESS: pi,
    copilot.HARNESS: copilot,
}


class UnknownTraceLocation(Exception):
    """A --file path outside every adapter's trace root."""


def infer_adapter(path: Path, home: Path):
    resolved = path.resolve()
    for adapter in ADAPTERS.values():
        if resolved.is_relative_to(adapter.trace_root(home).resolve()):
            return adapter
    raise UnknownTraceLocation(str(path))


class AuditData(BaseModel):
    invocations: list[Invocation] = Field(default_factory=list)
    unreadable: list[str] = Field(default_factory=list)
    drifted: dict[str, int] = Field(default_factory=dict)
    nested_reads: list[NestedRead] = Field(default_factory=list)
    nested_diagnostics: list[NestedDiagnostic] = Field(default_factory=list)
    evidence_scope: str = "all-retained-branches"
    inspected_files: list[str] = Field(default_factory=list)
    extraction_versions: dict[str, int] = Field(default_factory=dict)
    coverage_limits: list[str] = Field(default_factory=list)


def run_audit(
    home: Path,
    root: Path,
    global_mode: bool,
    harness: str | None,
    since: dt.datetime | None,
    last: bool = False,
) -> AuditData:
    cdir = cache.audit_cache_dir(home)
    data = AuditData()
    pi_snapshots: dict[str, PiExtractResult] = {}
    live_keys: set[str] = set()
    selected = [ADAPTERS[harness]] if harness else list(ADAPTERS.values())
    for adapter in ADAPTERS.values():
        for trace in adapter.discover(home):
            live_keys.add(cache.entry_key(trace))
    for adapter in selected:
        for trace in adapter.discover(home):
            data.extraction_versions[adapter.HARNESS] = adapter.VERSION
            entry = cache.load_entry(cdir, trace)
            if entry is None or entry.adapter_version != adapter.VERSION:
                try:
                    st = trace.stat()
                    result = adapter.extract(trace)
                except Exception:
                    data.unreadable.append(str(trace))
                    continue
                entry = cache.TraceCacheEntry(
                    trace_path=str(trace), mtime_ns=st.st_mtime_ns,
                    size=st.st_size, adapter=adapter.HARNESS,
                    adapter_version=adapter.VERSION,
                    recognized=result.recognized,
                    invocations=result.invocations,
                    pi_evidence=result if isinstance(result, PiExtractResult) else None,
                )
                cache.store_entry(cdir, entry)
            if entry.recognized == 0 and entry.size > 0:
                data.drifted[adapter.HARNESS] = data.drifted.get(adapter.HARNESS, 0) + 1
            data.inspected_files.append(str(trace))
            data.invocations.extend(entry.invocations)
            if entry.pi_evidence is not None:
                pi_snapshots[str(trace)] = entry.pi_evidence
    nested = reconcile_corpus(pi_snapshots)
    data.invocations = [i for i in data.invocations if i.harness != pi.HARNESS] + nested.invocations
    data.nested_reads = nested.nested_reads
    data.nested_diagnostics = nested.nested_diagnostics
    projects = {p: s.session_header.get("cwd") for p, s in pi_snapshots.items()}
    scope_files = {p for p in data.inspected_files
                   if global_mode or projects.get(p) == str(root.resolve())}
    data.nested_reads = [r for r in data.nested_reads if r.source_file in scope_files
                         and (since is None or r.result_record_time is None
                              or parse_ts(r.result_record_time) >= since)]
    data.nested_diagnostics = [d for d in data.nested_diagnostics if d.source_file in scope_files]
    cache.prune_vanished(cdir, live_keys)
    data.invocations = _filtered(data.invocations, root, global_mode, since)
    data.invocations.sort(key=lambda i: i.timestamp)
    if last:
        timed_sources = [(i.timestamp, i.source_file) for i in data.invocations]
        timed_sources += [(parse_ts(r.result_record_time), r.source_file)
                          for r in data.nested_reads if r.result_record_time is not None]
        newest = max(timed_sources)[1] if timed_sources else None
        data.invocations = [
            i for i in data.invocations if i.source_file == newest
        ]
        data.nested_reads = [r for r in data.nested_reads if r.source_file == newest]
        data.nested_diagnostics = [d for d in data.nested_diagnostics if d.source_file == newest]
    _qualify_coverage(data, pi.HARNESS in data.extraction_versions, since)
    return data


def run_audit_file(
    home: Path,
    path: Path,
    harness: str | None,
    since: dt.datetime | None,
    branch: str | None = None,
) -> AuditData:
    """Audit one explicit trace file: no cache, no project-scope filter."""
    adapter = ADAPTERS[harness] if harness else infer_adapter(path, home)
    result = adapter.extract(path)
    data = AuditData(inspected_files=[str(path)],
                     extraction_versions={adapter.HARNESS: adapter.VERSION})
    if isinstance(result, PiExtractResult):
        nested = reconcile_corpus({str(path): result})
        data.nested_reads = [r for r in nested.nested_reads
                             if since is None or r.result_record_time is None
                             or parse_ts(r.result_record_time) >= since]
        data.nested_diagnostics = nested.nested_diagnostics
    data.invocations = [
        i for i in (nested.invocations if isinstance(result, PiExtractResult) else result.invocations)
        if since is None or i.timestamp >= since
    ]
    if result.recognized == 0 and path.stat().st_size > 0:
        data.drifted[adapter.HARNESS] = 1
    if branch is not None:
        if not isinstance(result, PiExtractResult):
            raise ValueError("--branch requires a Pi trace")
        retained = set()
        current = branch
        while current is not None:
            if current in retained or current not in result.entry_parents:
                raise ValueError("Selected branch has missing, duplicate or cyclic ancestry")
            retained.add(current)
            current = result.entry_parents[current]
        data.invocations = [i for i in data.invocations if i.entry_id in retained
                            and (i.result_entry_id is None or i.result_entry_id in retained)]
        data.nested_reads = [r for r in data.nested_reads if r.occurrence[1] in retained]
        # Keep coverage diagnostics, including unavailable records, rather than
        # certifying a branch's coverage by discarding malformed evidence.
        data.evidence_scope = "selected-branch:" + branch
    data.invocations.sort(key=lambda i: i.timestamp)
    _qualify_coverage(data, isinstance(result, PiExtractResult), since)
    return data


def _filtered(
    invocations: list[Invocation],
    root: Path,
    global_mode: bool,
    since: dt.datetime | None,
) -> list[Invocation]:
    rp = str(root.resolve())
    munged = munge_path(rp)
    kept = []
    for inv in invocations:
        if since is not None and inv.timestamp < since:
            continue
        if not global_mode:
            if inv.project is not None:
                if inv.project != rp:
                    continue
            elif inv.harness == claude_code.HARNESS:
                if Path(inv.source_file).parent.name != munged:
                    continue
            else:
                continue
        kept.append(inv)
    return kept


def _qualify_coverage(data: AuditData, has_pi: bool, since: dt.datetime | None) -> None:
    if has_pi:
        data.coverage_limits.append(
            "Pi read coverage is unknown outside retained records: unprovided child logs, "
            "interrupted persistence, older runtimes and other readers are not covered")
    if data.nested_diagnostics:
        data.coverage_limits.append("Nested diagnostics qualify retained coverage; positive complete rows remain usable")
    if since is not None and any(r.result_record_time is None for r in data.nested_reads):
        data.coverage_limits.append("Untimed read occurrences retained; membership in requested time window is unknown")
    if has_pi and (data.unreadable or data.drifted.get(pi.HARNESS)):
        data.coverage_limits.append("Unreadable or unrecognized traces prevent confident unused classification")

    from drskill.traces.evidence import classify_reads
    classify_reads(data)
