"""Resource attribution and qualified combined counts, not workflow intent."""
from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

from drskill.traces.pipeline import AuditData
from drskill.traces.common import combined_use_id

REPORT_VERSION = 2


def classify_reads(data: AuditData) -> None:
    """Only a unique same-turn declared path relationship attributes support."""
    for row in data.nested_reads:
        wrappers = [i for i in data.invocations
                    if i.harness == "pi" and i.evidence_kind == "instruction-delivery"
                    and i.source_file == row.source_file and i.entry_id == row.turn_id]
        exact = [i for i in wrappers if row.resolved_path is not None
                 and i.resolved_path == row.resolved_path]
        support = [i for i in wrappers if row.resolved_path is not None
                   and row.resolved_path in i.declared_supporting_paths]
        if len(exact) == 1:
            row.evidence_kind = "skill-file-read"
            row.skill_name = exact[0].name
            delivery = exact[0]
            if delivery.combined_use_id is None:
                delivery.combined_use_id = combined_use_id(
                    delivery.evidence_owner[0] if delivery.evidence_owner else delivery.session_id,
                    delivery.turn_id, delivery.resolved_path)
            row.combined_use_id = delivery.combined_use_id
        elif len(support) == 1:
            row.evidence_kind = "supporting-read"
            row.skill_name = support[0].name
        elif row.resolved_path and PurePosixPath(row.resolved_path).name == "SKILL.md":
            row.evidence_kind = "skill-file-read"
            row.skill_name = PurePosixPath(row.resolved_path).parent.name
            qualification = "Resource label from recorded SKILL.md path; historical membership and invocation intent unproven"
            if qualification not in row.qualifications:
                row.qualifications.append(qualification)


def summary(data: AuditData) -> dict:
    kinds = Counter(i.evidence_kind for i in data.invocations if i.evidence_kind)
    kinds.update(r.evidence_kind for r in data.nested_reads if r.evidence_kind)
    combined = set()
    for index, inv in enumerate(data.invocations):
        if inv.harness != "pi" or inv.evidence_kind not in ("instruction-delivery", "skill-file-read"):
            continue
        if inv.inheritance == "unresolved":
            continue
        combined.add(inv.combined_use_id or inv.evidence_owner or ("invocation", inv.source_file, index))
    unresolved = 0
    owners = set()
    for row in data.nested_reads:
        if row.execution_owner is None:
            unresolved += 1
        else:
            owners.add(row.execution_owner)
            if row.evidence_kind == "skill-file-read":
                combined.add(row.combined_use_id or ("nested", row.execution_owner))
    return {
        "instruction_deliveries": kinds["instruction-delivery"],
        "skill_file_reads": kinds["skill-file-read"],
        "supporting_reads": kinds["supporting-read"],
        "native_read_occurrences": sum(i.evidence_kind in ("skill-file-read", "supporting-read")
                                       for i in data.invocations),
        "native_distinct_read_executions": len({i.evidence_owner for i in data.invocations
                                               if i.evidence_kind in ("skill-file-read", "supporting-read")
                                               and i.evidence_owner is not None}),
        "native_unresolved_occurrences": sum(i.inheritance == "unresolved"
                                             for i in data.invocations if i.evidence_kind),
        "nested_read_occurrences": len(data.nested_reads),
        "nested_distinct_executions": len(owners),
        "nested_inherited_occurrences": sum(r.inheritance == "inherited" for r in data.nested_reads),
        "nested_unresolved_occurrences": unresolved,
        "combined_observed_uses": len(combined),
        "qualification": "Combined uses are observations, not workflow starts or completion; unresolved nested occurrences excluded",
    }
