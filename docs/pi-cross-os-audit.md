# Explicit Windows-and-WSL audit corpus (ticket 04)

Implementation repository: `/home/jack/git/drskill`, branch `local/pi-support`.
Owner-confirmed public seams: explicit corpus API, audit CLI and existing
human/JSON reports. Review baseline:
`5b559e017b710ce9b22e10aa407b247a04305a41`.

## Ticket 05 interfaces

Run from the canonical project root. Supply a bounded list of physical logs;
repeating `--file` does not discover other distributions, parents, children,
or remote services.

```sh
uv run drskill audit --harness pi \
  --file /path/exported-windows-session.jsonl \
  --file /path/wsl-session.jsonl \
  --since 2026-10-01T00:00:00Z --until 2026-10-08T00:00:00Z
# Identical corpus/policy, machine-readable:
uv run drskill audit --harness pi \
  --file /path/exported-windows-session.jsonl \
  --file /path/wsl-session.jsonl \
  --since 2026-10-01T00:00:00Z --until 2026-10-08T00:00:00Z --json
```

These are command templates, not results of a personal-machine assessment.
This work uses sanitized regressions only; deployment and that assessment
remain ticket 05's responsibility. It does not reinterpret the prior 2,201
summed observations as a common-window execution census.

For exported logs whose retained `parentSession` names a recorded source rather
than its current physical location, explicitly supply established export
provenance:

```sh
uv run drskill audit --harness pi \
  --file /exports/parent.jsonl --file /exports/child.jsonl \
  --source-location '/exports/parent.jsonl=C:\Sessions\parent.jsonl' \
  --since 2026-10-01 --until 2026-10-08 --json
```

A mapping is an operator provenance declaration, not authenticated OS access.
Use it only when the export/source relationship is known. It never maps skill
resources between OSes and never authorizes opening the declared location.
Relative parent references resolve lexically against the declared source's
directory, or the physical directory when there is no declaration.
Duplicate declared locations remain ambiguous. Same session IDs, equal paths
or equal filenames do not establish ancestry. Missing, conflicting or cyclic
ancestry stays unresolved. Ownership requires matching retained entry/call
identity and matching payload evidence across the supplied ancestry.

Python callers use the existing pipeline module:

```python
from drskill.traces.pipeline import run_audit_files

data = run_audit_files(
    home, [windows_export, wsl_log], "pi", since=start_utc, until=end_utc,
    source_locations={str(windows_export): recorded_windows_location},
)
```

`source_locations` is optional. The corpus API caches extraction by physical
file, adapter version and cache schema; it recomputes ownership, attribution,
window policy and summaries every time. Changing/removing a supplied ancestor
or changing a declaration cannot preserve stale inherited ownership. Explicit
audits do not prune unrelated cache entries. The existing `run_audit_file`
convenience API remains uncached.

## Policy and output contract

- One half-open UTC window `[since, until)`. ISO timestamps must explicitly be
  UTC; date-only boundaries mean UTC midnight. `--since 30d` remains supported,
  but absolute boundaries are recommended for repeatable ticket 05 reports.
- All retained raw branches across the corpus. `--branch` still selects raw
  ancestry for exactly one Pi file, retaining report-wide diagnostics.
- Read membership uses result-record time, not native/nested call start time.
  Wrapper membership uses delivery-record time. Missing times stay visible with
  `window_membership: "unknown"`; unknown rows are not certified in-window.
  Out-of-window retained declarations/ancestors can still qualify displayed rows.
- Physical paths, recorded cwd namespace and recorded OS are separate.
  Storage on Linux does not prove WSL execution; POSIX cwd does not prove WSL
  either. Missing OS/runtime versions remain unknown. Session format version
  is not the producer/runtime version.
- Delivery, skill-file reads, declared supporting reads and unattributed nested
  reads remain separate. Combined observations are not workflow starts,
  completion or authenticated historical membership.
- Current inventory is deliberately not joined in an explicit corpus view.
  Same-named resources keep their recorded paths; path equality/current byte
  equality does not authenticate historical installations or versions.
  Pi coverage limits continue to prevent confident unused classifications.

Report version **4**, Pi extraction **13**, cache schema **3**. Incompatible
extractions are re-read; no report totals or reconciled ownership are cached.

JSON retains prior fields and adds `window`, `sources`, `source_summaries`,
native `tool_call_id`/`result_record_time` and row `window_membership`.
Sources retain physical and declared recorded locations, cwd namespace, recorded
OS, session/parent identity, format/producer/extraction versions, source snapshot
hash and inspected-record counts. Producer fields absent in original logs remain
null/absent. Native rows retain call and result locators/times separately.

`evidence_summary` is the reconciled aggregate. `source_summaries` contains
displayed physical-source counts, including inherited/unresolved and untimed
counts. Per-source distinct/combined sets can overlap inherited owners and must
not simply be added. Inspected-record coverage is separate from displayed
activity, including in named drilldowns. Human reports preserve these policies,
per-source totals, aggregate totals and coverage qualifications.

## Validation and review

Regressions: `tests/test_traces_explicit_corpus.py` exercises disjoint corpora,
cross-location inherited copies and relocated context, missing/ambiguous
ancestors, contradictory payloads and same-ID conflicts, Windows nested support,
untimed/native result-time windows, source/aggregate CLI reports, cache hits and
incompatible contract re-extraction. Existing Windows resource/path regressions
continue to cover nested SKILL.md reads without Windows/WSL aliases.

Focused command:
`uv run pytest tests/test_traces_*.py tests/test_cli_audit.py -q`.

Syntax command:
`uv run python -m compileall -q src/drskill`.
No typechecking/lint gate is declared in `pyproject.toml`; syntax compilation is
not typechecking. No optional dependencies are installed by this task.

Final focused/full results, two-axis review and commits are recorded below after
validation. Coordinator ticket status is not edited from this project session.
