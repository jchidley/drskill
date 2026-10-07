"""Read-only retained-corpus comparison; stdout contains aggregate metadata only."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import ntpath
import os
from pathlib import Path
import tempfile

from drskill.traces.evidence import REPORT_VERSION
from drskill.traces.pipeline import run_audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path, required=True)
    args = parser.parse_args()
    if not args.sessions_root.is_dir():
        parser.error("--sessions-root must be an explicitly supplied retained Pi session directory")
    raw = args.baseline_report.read_bytes()
    baseline = json.loads(raw)
    rows = [r for r in baseline["nested_reads"] if r["resolved_path"] is None
            and r["evidence_kind"] is None]
    # Filename plus occurrence permits comparing physical locators without
    # inventing Windows/WSL resource-path or ancestry equivalence.
    def key(row):
        return (ntpath.basename(row["source_file"]), *row["occurrence"])

    previous = os.environ.get("PI_CODING_AGENT_SESSION_DIR")
    os.environ["PI_CODING_AGENT_SESSION_DIR"] = str(args.sessions_root.resolve())
    try:
        with tempfile.TemporaryDirectory(prefix="drskill-windows-reaudit-") as home:
            current = run_audit(Path(home), Path.cwd(), True, "pi", None)
    finally:
        if previous is None:
            os.environ.pop("PI_CODING_AGENT_SESSION_DIR", None)
        else:
            os.environ["PI_CODING_AGENT_SESSION_DIR"] = previous
    indexed = {}
    for read in current.nested_reads:
        row = read.model_dump()
        identity = key(row)
        if identity in indexed:
            raise ValueError("Ambiguous physical occurrence in supplied corpus")
        indexed[identity] = row
    matched = []
    for old in rows:
        new = indexed.get(key(old))
        if new is None or any(new[field] != old[field] for field in
                              ("requested_path", "result_record_time", "source_line")):
            raise ValueError("Baseline occurrence missing or changed; comparison cannot be certified")
        matched.append(new)
    print(json.dumps({
        "baseline_sha256": hashlib.sha256(raw).hexdigest(),
        "baseline_report_version": baseline["report_version"],
        "baseline_extraction_versions": baseline["extraction_versions"],
        "report_version": REPORT_VERSION,
        "extraction_versions": current.extraction_versions,
        "inspected_files": len(current.inspected_files),
        "baseline_unresolved_unclassified_nested_reads": len(rows),
        "same_occurrences_compared": len(matched),
        "now_resolved": sum(r["resolved_path"] is not None for r in matched),
        "classifications": dict(Counter(r["evidence_kind"] or "unattributed" for r in matched)),
        "ownership": dict(Counter(r["inheritance"] for r in matched)),
        "qualification": (
            "Baseline displayed occurrences, not a new moving time window; "
            "lexical attribution is not historical inventory identity, OS access or completion. "
            "Windows parentSession links are not mapped to WSL."
        ),
    }, indent=2))


if __name__ == "__main__":
    main()
