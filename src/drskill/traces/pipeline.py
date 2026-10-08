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
    extract_corpus as extract_pi_nested_corpus,  # public ticket 02 extraction seam
)
from drskill.traces.common import parse_ts, resolve_read_path

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
    window: dict = Field(default_factory=dict)
    sources: dict[str, dict] = Field(default_factory=dict)


def _load_or_extract(cdir: Path, path: Path, adapter, use_cache: bool = True) -> cache.TraceCacheEntry:
    entry = cache.load_entry(cdir, path) if use_cache else None
    if entry is not None and entry.adapter == adapter.HARNESS and entry.adapter_version == adapter.VERSION:
        return entry
    st = path.stat()
    extracted = adapter.extract(path)
    entry = cache.TraceCacheEntry(
        trace_path=str(path), mtime_ns=st.st_mtime_ns, size=st.st_size,
        adapter=adapter.HARNESS, adapter_version=adapter.VERSION,
        recognized=extracted.recognized, invocations=extracted.invocations,
        pi_evidence=extracted if isinstance(extracted, PiExtractResult) else None)
    if use_cache:
        cache.store_entry(cdir, entry)
    return entry


def _source_metadata(path: Path, entry: cache.TraceCacheEntry,
                     recorded_location: str | None = None) -> dict:
    header = entry.pi_evidence.session_header if entry.pi_evidence else {}
    cwd = header.get("cwd")
    normalized, quals = resolve_read_path(cwd, None) if isinstance(cwd, str) else (None, [])
    return {
        "physical_location": str(path),
        "recorded_location": recorded_location,
        "recorded_os": header.get("os"),
        "recorded_cwd": cwd,
        "path_namespace": ("windows" if normalized and (
            normalized.startswith("//") or len(normalized) > 1 and normalized[1] == ":")
            else "posix" if normalized else "unknown"),
        "session_id": header.get("id"),
        "parent_session": header.get("parentSession"),
        "session_format_version": header.get("version"),
        "producer_version": header.get("agentVersion") or header.get("runtimeVersion"),
        "producer_metadata": {k: header[k] for k in ("runtimeVersion", "producer", "agentVersion") if k in header},
        "extraction_version": entry.adapter_version,
        "qualifications": quals + ["Storage location does not establish execution OS; cwd namespace is lexical"],
        "source_sha256": entry.pi_evidence.source_sha256 if entry.pi_evidence else None,
        "inspected_records": entry.pi_evidence.inspected_records if entry.pi_evidence else None,
        "inspected_invocations": len(entry.invocations),
        "inspected_nested_reads": len(entry.pi_evidence.nested_reads) if entry.pi_evidence else 0,
    }


def run_audit(
    home: Path,
    root: Path,
    global_mode: bool,
    harness: str | None,
    since: dt.datetime | None,
    last: bool = False,
    until: dt.datetime | None = None,
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
            try:
                entry = _load_or_extract(cdir, trace, adapter)
            except Exception:
                data.unreadable.append(str(trace))
                continue
            if entry.recognized == 0 and entry.size > 0:
                data.drifted[adapter.HARNESS] = data.drifted.get(adapter.HARNESS, 0) + 1
            data.inspected_files.append(str(trace))
            data.sources[str(trace)] = _source_metadata(trace, entry)
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
    data.nested_reads = [r for r in data.nested_reads if r.source_file in scope_files]
    data.nested_diagnostics = [d for d in data.nested_diagnostics if d.source_file in scope_files]
    cache.prune_vanished(cdir, live_keys)
    data.invocations = _filtered(data.invocations, root, global_mode, None)
    _apply_window(data, since, until)
    if last:
        timed_sources = [(observation_time(i), i.source_file) for i in data.invocations
                         if observation_time(i) is not None]
        timed_sources += [(parse_ts(r.result_record_time), r.source_file)
                          for r in data.nested_reads if r.result_record_time is not None]
        newest = max(timed_sources)[1] if timed_sources else None
        data.invocations = [
            i for i in data.invocations if i.source_file == newest
        ]
        data.nested_reads = [r for r in data.nested_reads if r.source_file == newest]
        data.nested_diagnostics = [d for d in data.nested_diagnostics if d.source_file == newest]
    _qualify_coverage(data, pi.HARNESS in data.extraction_versions, since or until)
    return data


def run_audit_files(
    home: Path,
    paths: list[Path],
    harness: str | None,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    source_locations: dict[str, str] | None = None,
    branch: str | None = None,
    use_cache: bool = True,
) -> AuditData:
    """Audit only supplied files; cache extraction, never reconciled ownership.

    Source locations are explicit provenance declarations for relocated logs,
    not OS aliases or permission to open another file.
    """
    for boundary in (since, until):
        if boundary is not None and boundary.utcoffset() != dt.timedelta(0):
            raise ValueError("Window boundaries must be aware UTC timestamps")
    if since is not None and until is not None and since >= until:
        raise ValueError("Window requires since < until")
    if not paths:
        raise ValueError("At least one explicit trace file is required")
    if branch is not None and len(set(p.resolve() for p in paths)) != 1:
        raise ValueError("--branch requires exactly one explicit file")
    data = AuditData()
    snapshots = {}
    cdir = cache.audit_cache_dir(home)
    locations = {str(Path(p).resolve()): v for p, v in (source_locations or {}).items()}
    supplied = sorted(set(p.resolve() for p in paths))
    if set(locations) - {str(p) for p in supplied}:
        raise ValueError("Source location must name a supplied physical file")
    for path in supplied:
        adapter = ADAPTERS[harness] if harness else infer_adapter(path, home)
        entry = _load_or_extract(cdir, path, adapter, use_cache)
        data.inspected_files.append(str(path))
        data.extraction_versions[adapter.HARNESS] = adapter.VERSION
        if not entry.recognized and entry.size:
            data.drifted[adapter.HARNESS] = data.drifted.get(adapter.HARNESS, 0) + 1
        if entry.pi_evidence is not None:
            snapshots[str(path)] = entry.pi_evidence
        else:
            data.invocations.extend(entry.invocations)
        data.sources[str(path)] = _source_metadata(path, entry, locations.get(str(path)))
    nested = reconcile_corpus(snapshots, source_locations=locations)
    data.invocations.extend(nested.invocations)
    data.nested_reads = nested.nested_reads
    data.nested_diagnostics = nested.nested_diagnostics
    if branch is not None:
        if len(snapshots) != 1:
            raise ValueError("--branch requires a Pi trace")
        result = next(iter(snapshots.values()))
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
        data.evidence_scope = "selected-branch:" + branch
    _apply_window(data, since, until)
    _qualify_coverage(data, bool(snapshots), since or until)
    if locations:
        data.coverage_limits.append("Recorded source locations are supplied provenance declarations; ancestry qualification is conditional on their accuracy")
    return data


def observation_time(inv: Invocation) -> dt.datetime | None:
    """Native reads use result-record time, never substitute call time."""
    if inv.harness == pi.HARNESS and inv.result_entry_id is not None:
        return parse_ts(inv.result_record_time)
    return inv.timestamp


def _apply_window(data: AuditData, since: dt.datetime | None, until: dt.datetime | None) -> None:
    from drskill.traces.evidence import classify_reads
    classify_reads(data)
    data.window = {
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "policy": "[since, until) UTC; untimed membership unknown",
        "time_basis": "Pi result-record time for reads, delivery-record time for wrappers",
    }
    def retained(time):
        return time is None or ((since is None or time >= since) and (until is None or time < until))
    for inv in data.invocations:
        inv.window_membership = "inside" if observation_time(inv) is not None else "unknown"
    for row in data.nested_reads:
        row.window_membership = "inside" if parse_ts(row.result_record_time) is not None else "unknown"
    data.invocations = [i for i in data.invocations if retained(observation_time(i))]
    data.nested_reads = [r for r in data.nested_reads if retained(parse_ts(r.result_record_time))]
    data.invocations.sort(key=lambda i: (i.timestamp is not None, i.timestamp or dt.datetime.min))


def run_audit_file(
    home: Path,
    path: Path,
    harness: str | None,
    since: dt.datetime | None,
    branch: str | None = None,
) -> AuditData:
    """Single-file convenience interface; preserves uncached extraction."""
    return run_audit_files(home, [path], harness, since, branch=branch, use_cache=False)


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
        if since is not None and observation_time(inv) is not None and observation_time(inv) < since:
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
    if since is not None and (any(r.result_record_time is None for r in data.nested_reads)
                              or any(observation_time(i) is None for i in data.invocations)):
        data.coverage_limits.append("Untimed read occurrences retained; membership in requested time window is unknown")
    if has_pi and (data.unreadable or data.drifted.get(pi.HARNESS)):
        data.coverage_limits.append("Unreadable or unrecognized traces prevent confident unused classification")
