"""Aggregate invocation records and render the audit report and drill-down."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from pydantic import BaseModel
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from drskill.report import _sanitize
from drskill.text import one_line
from drskill.traces.model import Invocation
from drskill.traces.pipeline import AuditData, observation_time

MIN_SPAN_DAYS = 7.0
HEURISTIC_LEGEND = "~ observed delivery or SKILL.md reads, not authenticated invocation intent"


class NameStats(BaseModel):
    kind: str
    name: str
    server: str | None = None
    resource: str = ""
    count: int = 0  # main-thread uses
    sidechain: int = 0
    sessions: int = 0
    last_used: dt.datetime | None
    heuristic: bool = False


class Coverage(BaseModel):
    harness: str
    first: dt.datetime
    last: dt.datetime
    sessions: int
    invocations: int

    @property
    def span_days(self) -> float:
        span = (self.last - self.first).total_seconds() / 86400
        return max(span, MIN_SPAN_DAYS)


def _key(inv: Invocation) -> tuple:
    resource = ""
    if inv.harness == "pi" and inv.evidence_kind:
        resource = inv.resolved_path or f"unknown:{inv.source_file}:{inv.entry_id}"
    return (inv.kind, inv.name, inv.server, resource)


def aggregate(invocations: list[Invocation]) -> dict[str, list[NameStats]]:
    grouped: dict[str, dict[tuple, list[Invocation]]] = defaultdict(lambda: defaultdict(list))
    for inv in invocations:
        grouped[inv.harness][_key(inv)].append(inv)
    out: dict[str, list[NameStats]] = {}
    for harness, names in grouped.items():
        stats = []
        for (kind, name, server, resource), invs in names.items():
            stats.append(NameStats(
                kind=kind, name=name, server=server, resource=resource,
                count=len({i.combined_use_id or i.evidence_owner or ("row", n)
                           for n, i in enumerate(invs)
                           if not i.sidechain and i.evidence_kind != "supporting-read"
                           and i.inheritance != "unresolved"}),
                sidechain=sum(1 for i in invs if i.sidechain),
                sessions=len({i.session_id for i in invs}),
                last_used=max((observation_time(i) for i in invs if observation_time(i) is not None), default=None),
                heuristic=any(i.detection != "explicit" for i in invs),
            ))
        stats.sort(key=lambda s: (-s.count, s.name))
        out[harness] = stats
    return out


def coverage(invocations: list[Invocation]) -> dict[str, Coverage]:
    grouped: dict[str, list[Invocation]] = defaultdict(list)
    for inv in invocations:
        if observation_time(inv) is not None:
            grouped[inv.harness].append(inv)
    return {
        harness: Coverage(
            harness=harness,
            first=min(observation_time(i) for i in invs),
            last=max(observation_time(i) for i in invs),
            sessions=len({i.session_id for i in invs}),
            invocations=len(invs),
        )
        for harness, invs in grouped.items()
    }


def rollup(invocations: list[Invocation]) -> list[tuple[NameStats, float]]:
    per_harness = aggregate(invocations)
    cov = coverage(invocations)
    merged: dict[tuple, NameStats] = {}
    rates: dict[tuple, float] = defaultdict(float)
    for harness, stats in per_harness.items():
        weeks = cov[harness].span_days / 7.0 if harness in cov else 1.0
        for s in stats:
            key = (s.kind, s.name, s.server, s.resource)
            rates[key] += s.count / weeks
            if key in merged:
                m = merged[key]
                merged[key] = m.model_copy(update={
                    "count": m.count + s.count,
                    "sidechain": m.sidechain + s.sidechain,
                    "sessions": m.sessions + s.sessions,
                    "last_used": max((t for t in (m.last_used, s.last_used) if t is not None), default=None),
                    "heuristic": m.heuristic or s.heuristic,
                })
            else:
                merged[key] = s
    ranked = [(merged[k], rates[k]) for k in merged]
    ranked.sort(key=lambda pair: (-pair[1], pair[0].name))
    return ranked


def _clean(text: str) -> str:
    return escape(_sanitize(text))


def _get_via_text(inv: Invocation) -> str:
    """Generate the 'via' text based on detection type."""
    if inv.detection == "explicit":
        return "explicit tool call"
    elif inv.detection == "command-marker":
        if inv.harness == "pi":
            return "expanded instruction delivery (not authenticated UI command)"
        return f"/{_clean(inv.name)} slash command"
    elif inv.detection == "skill-read":
        return "SKILL.md read"
    else:
        return "unknown"


def _uses_cell(s: NameStats) -> str:
    if s.sidechain:
        return f"{s.count} (+{s.sidechain} subagent)"
    return str(s.count)


def render_audit(console: Console, data: AuditData) -> None:
    per_harness = aggregate(data.invocations)
    cov = coverage(data.invocations)
    any_heuristic = False
    for harness in sorted(per_harness):
        c = cov.get(harness)
        if c is not None:
            console.print(
                f"\n[bold]{_clean(harness)}[/bold]  coverage: displayed timed activity "
                f"{c.first.date().isoformat()} to {c.last.date().isoformat()} · "
                f"{c.sessions} sessions · {c.invocations} timed rows")
        else:
            console.print(f"\n[bold]{_clean(harness)}[/bold]  coverage: displayed timed activity unknown")
        table = Table(show_edge=False, pad_edge=False)
        for col in ("name", "kind", "server", "uses", "share", "sessions", "last used"):
            table.add_column(col)
        if harness == "pi":
            table.add_column("recorded resource (not installation identity)")
        total_main = sum(s.count for s in per_harness[harness]) or 1
        for s in per_harness[harness]:
            marker = " ~" if s.heuristic else ""
            any_heuristic = any_heuristic or s.heuristic
            cells = [
                _clean(s.name) + marker,
                s.kind.replace("mcp_tool", "tool"),
                _clean(s.server or ""),
                _uses_cell(s),
                f"{100 * s.count / total_main:.0f}%",
                str(s.sessions),
                s.last_used.date().isoformat() if s.last_used else "unknown",
            ]
            if harness == "pi":
                cells.append(_clean(s.resource))
            table.add_row(*cells)
        console.print(table)
    if any_heuristic:
        console.print(f"[dim]{HEURISTIC_LEGEND}[/dim]")
    if len(per_harness) > 1:
        spans = {h: cov[h].span_days for h in per_harness if h in cov}
        if spans and max(spans.values()) / min(spans.values()) > 2:
            parts = ", ".join(f"{_clean(h)} {spans[h]:.0f}d" for h in sorted(spans))
            console.print(
                f"[dim]windows differ ({parts}); ranks compare rates, "
                "not raw counts[/dim]"
            )
        console.print("\n[bold]all harnesses[/bold]")
        table = Table(show_edge=False, pad_edge=False)
        for col in ("name", "kind", "uses", "/wk", "last used"):
            table.add_column(col)
        for s, rate in rollup(data.invocations):
            marker = " ~" if s.heuristic else ""
            table.add_row(_clean(s.name) + marker,
                          s.kind.replace("mcp_tool", "tool"),
                          _uses_cell(s), f"{rate:.1f}",
                          s.last_used.date().isoformat() if s.last_used else "unknown")
        console.print(table)
    if not data.invocations:
        if data.nested_reads:
            console.print("no direct skill or MCP invocation rows; nested read evidence follows")
        else:
            console.print("no skill or MCP tool invocations found in trace history")
    render_evidence(console, data)
    _footer(console, data)


def _footer(console: Console, data: AuditData) -> None:
    if data.unreadable:
        n = len(data.unreadable)
        console.print(
            f"[dim]{n} trace file{'s' if n != 1 else ''} unreadable "
            "(--json lists them)[/dim]"
        )
    for harness, n in sorted(data.drifted.items()):
        console.print(
            f"[dim]{_clean(harness)}: {n} session file{'s' if n != 1 else ''} "
            "held no recognized events[/dim]"
        )


def matches(inv: Invocation, name: str) -> bool:
    if inv.name == name:
        return True
    if ":" in name:
        server, _, tool = name.partition(":")
        return inv.kind == "mcp_tool" and inv.server == server and inv.name == tool
    return False


def render_drilldown(console: Console, name: str, data: AuditData) -> None:
    hits = [i for i in data.invocations if matches(i, name)]
    if not hits:
        render_evidence(console, data, name)
        console.print(f"no invocations of {_clean(name)} found in direct rows")
        _footer(console, data)
        return
    groups: dict[tuple, list[Invocation]] = defaultdict(list)
    for inv in hits:
        groups[_key(inv)].append(inv)
    for (kind, gname, server, resource), invs in sorted(groups.items()):
        label = f"{gname} ({kind.replace('mcp_tool', 'MCP tool')}"
        label += f", server {server})" if server else ")"
        if resource:
            label += f" · {resource}"
        by_harness = defaultdict(int)
        for i in invs:
            by_harness[i.harness] += 1
        counts = ", ".join(f"{_clean(h)} {n}" for h, n in sorted(by_harness.items()))
        console.print(f"\n[bold]{_clean(label)}[/bold]  {counts}")
        for inv in sorted(invs, key=lambda i: (i.timestamp is not None, i.timestamp or dt.datetime.min), reverse=True):
            time = observation_time(inv)
            when = time.strftime("%Y-%m-%d %H:%M") if time else "unknown time"
            where = inv.project or "unknown project"
            side = "  [dim](subagent)[/dim]" if inv.sidechain else ""
            console.print(f"  {when}  {_clean(inv.harness)}  {_clean(where)}{side}")
            console.print(f"    [dim]via: {_get_via_text(inv)}[/dim]")
            if inv.requested_path:
                console.print(f"    requested: {_clean(inv.requested_path)}")
            if inv.evidence_kind:
                console.print(f"    ownership: {_clean(inv.inheritance or 'unknown')} · "
                              f"owner: {_clean(str(inv.evidence_owner))}")
            if inv.result_entry_id:
                console.print(f"    result: {_clean(inv.result_entry_id)} line {inv.result_source_line}")
            for qualification in inv.qualifications:
                console.print(f"    [dim]{_clean(qualification)}[/dim]")
            if inv.query:
                console.print(f"    query: {_clean(inv.query)}")
            if inv.reasoning:
                console.print(f"    reasoning: {_clean(one_line(inv.reasoning, 200))}")
            trace = (f"{inv.source_file}:{inv.source_line}"
                     if inv.source_line is not None else inv.source_file)
            console.print(f"    [dim]trace: {_clean(trace)}[/dim]")
    render_evidence(console, data, name)
    _footer(console, data)


def render_evidence(console: Console, data: AuditData, name: str | None = None) -> None:
    from drskill.traces.evidence import REPORT_VERSION, summary
    from drskill.traces.cache import CACHE_VERSION
    selected = data if name is None else data.model_copy(update={
        "invocations": [i for i in data.invocations if matches(i, name)],
        "nested_reads": [r for r in data.nested_reads if r.skill_name == name],
    })
    counts = summary(selected)
    if data.extraction_versions.get("pi") is None and not data.nested_reads:
        return
    console.print(f"\nEvidence scope: {_clean(data.evidence_scope)}")
    if data.window:
        console.print(f"Window: [{_clean(data.window.get('since') or 'unbounded')}, "
                      f"{_clean(data.window.get('until') or 'unbounded')}) UTC · untimed membership unknown")
    from drskill.traces.evidence import source_summaries
    for path, source_counts in source_summaries(selected).items():
        source = data.sources.get(path, {})
        console.print(f"Source: {_clean(path)} · namespace {_clean(source.get('path_namespace', 'unknown'))} · "
                      f"recorded OS {_clean(str(source.get('recorded_os') or 'unknown'))}")
        console.print(f"  inspected records: {source.get('inspected_records', 'unknown')} · "
                      f"inspected: {source.get('inspected_invocations', 'unknown')} direct rows / "
                      f"{source.get('inspected_nested_reads', 'unknown')} nested reads; "
                      f"displayed: {source_counts['instruction_deliveries']} deliveries / "
                      f"{source_counts['skill_file_reads']} skill reads / "
                      f"{source_counts['supporting_reads']} supporting / "
                      f"{source_counts['unattributed_reads']} unattributed · "
                      f"{source_counts['combined_observed_uses']} qualified combined observations")
        console.print(f"  nested ownership: {source_counts['nested_inherited_occurrences']} inherited / "
                      f"{source_counts['nested_unresolved_occurrences']} unresolved")
        if source.get("recorded_location"):
            console.print(f"  declared recorded source: {_clean(source['recorded_location'])}")
    if data.sources:
        console.print("Recorded resources are not joined to current inventory; paths and current byte equality "
                      "do not authenticate historical installations or versions.")
        console.print("Per-source distinct counts overlap inherited owners; aggregate is reconciled, not their sum. "
                      "Storage location does not establish execution OS.")
    console.print(f"Evidence versions: report {REPORT_VERSION} · "
                  f"Pi extraction {data.extraction_versions.get('pi', 'unknown')} · cache schema {CACHE_VERSION}")
    console.print("Path matching: lexical recorded namespace, case-sensitive; Windows "
                  "separators/drive letter normalized; no Windows/WSL mapping or OS-access attestation")
    console.print(
        f"Instruction deliveries: {counts['instruction_deliveries']} · "
        f"skill-file reads: {counts['skill_file_reads']} · "
        f"declared supporting reads: {counts['supporting_reads']} · "
        f"unattributed reads: {counts['unattributed_reads']}"
    )
    console.print(
        f"Native reads: {counts['native_read_occurrences']} physical occurrences · "
        f"{counts['native_distinct_read_executions']} distinct executions · "
        f"{counts['native_unresolved_occurrences']} unresolved native/delivery observations"
    )
    console.print(
        f"Nested reads: {counts['nested_read_occurrences']} physical occurrences · "
        f"{counts['nested_distinct_executions']} distinct executions · "
        f"{counts['nested_inherited_occurrences']} inherited · "
        f"{counts['nested_unresolved_occurrences']} unresolved"
    )
    console.print(f"Combined observed uses: {counts['combined_observed_uses']} (not workflow completion)")
    console.print(f"Unknown window membership: {counts['untimed_invocations']} direct rows / "
                  f"{counts['untimed_nested_reads']} nested reads")
    console.print("Inspected source records and displayed activity are separate; untimed rows "
                  "are retained, not certified inside the window.")
    for row in selected.nested_reads:
        console.print(f"  {_clean(row.skill_name or 'unattributed read')} · "
                      f"{_clean(row.evidence_kind or 'unattributed')} · {_clean(row.inheritance)}")
        console.print(f"    requested: {_clean(row.requested_path)}")
        console.print(f"    resolved: {_clean(row.resolved_path or 'unknown')}")
        console.print(f"    result-record time: {_clean(row.result_record_time or 'unknown')}")
        console.print(f"    trace: {_clean(row.source_file)}:{row.source_line} · "
                      f"result {_clean(row.occurrence[1])} · parent {_clean(row.result_parent_id or 'unknown')}")
        console.print(f"    snapshot: {_clean(row.source_sha256)} · owner: {_clean(str(row.execution_owner))}")
        if row.provenance:
            console.print(f"    fixture provenance: {_clean(str(row.provenance))}")
        for qualification in row.qualifications:
            console.print(f"    [dim]{_clean(qualification)}[/dim]")
    if name is not None and data.nested_diagnostics:
        console.print("[dim]Report-wide coverage diagnostics (not attributed to this name):[/dim]")
    for diagnostic in data.nested_diagnostics:
        console.print(f"  [dim]{_clean(diagnostic.code)}: {_clean(diagnostic.detail)} "
                      f"({_clean(diagnostic.source_file)}:{diagnostic.source_line})[/dim]")
    for limit in data.coverage_limits:
        console.print(f"[dim]Coverage: {_clean(limit)}[/dim]")
