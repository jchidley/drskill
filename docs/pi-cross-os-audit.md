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

## Final parent validation

- `uv run pytest tests/test_traces_*.py tests/test_cli_audit.py -q`:
  **229 passed**.
- Full suite, run once by the parent after behavioral corrections:
  `uv run pytest -q` — **1,263 passed, 7 failed**.
  Two deep tests fail because `litellm` is missing; five MCP-connect tests
  fail because `mcp` is missing. These match the prior handoff's optional-extra
  failures. No extras were installed. **The full-suite gate is not green.**
  Local evidence: `/tmp/drskill-ticket04-pytest-final.log`.
- `uv run python -m compileall -q src/drskill`: passed.
- The focused run's subsequent `git diff --check` caught an extra trailing blank
  line in the test file. Removed afterward; no behavioral changes followed
  the full-suite run. Final whitespace validation is recorded at commit time.
- No configured typechecking or lint gate was run. Compilation is syntax
  validation only.

The Spec reviewer independently ran the full suite on committed `26bf44d`,
reporting 1,260 passed and the same seven optional-extra failures. The parent's
final run above includes three post-review regressions and supersedes that count.

## Standards review

Separate fresh DeepSeek review of `26bf44d` against the confirmed baseline:
two documentation concerns and four heuristic smell categories; no functional
defect reported.

- The missing-ancestor coverage concern was not confirmed: the cross-location
  cache regression already removes the supplied ancestor. Added an explicit
  `ancestry-missing-parent` assertion to make it unambiguous.
- The pending validation-record concern is resolved by this section.
- Consolidated repeated cache load/extract/store policy in `_load_or_extract`.
- The purported dead import was independently disproved: existing public
  callers/tests import `extract_pi_nested_corpus` from the pipeline. A trial
  removal caused seven focused failures; restored and documented the re-export.
- Retained separate native/nested ownership update code: both use the shared
  `verified_owner` policy but have different row contracts. Retained the small
  JSON metadata dictionaries; introducing a second typed reporting domain is
  not required by this bounded feature. These are heuristic maintainability
  suggestions, not demonstrated failures.

## Spec review

Separate fresh DeepSeek review of committed `26bf44d`: three actionable
report/documentation findings and one explicitly non-violating interpretation;
no incorrect ancestry, cache ownership or aggregate behavior reported.

- Final validation/review/task-commit evidence is recorded here.
- Directory-scan source metadata was missing despite being available in cached
  snapshots. Reproduced with a failing existing-CLI regression; both scan and
  explicit corpus now share `_source_metadata`.
- Inspected records counted raw lines. Reproduced with blank/malformed lines;
  now counts parsed object records, retaining malformed-line diagnostics.
- Unknown Windows case policy deliberately remains case-sensitive rather than
  guessing alias equivalence. No change.
- Parent additionally reproduced an invented weekly rate for untimed-only
  activity; rates now remain unknown whenever their activity includes untimed
  rows. The public report regression verifies this.

Both reviews are cross-family relative to the OpenAI author. Their original
findings are kept separate above; review follow-ups were independently checked
by the parent through the stated public regressions and final validation.

## Task commits and handoff limits

- `26bf44d`: explicit cross-OS corpus, report contract and public regressions.
- Follow-up commit: review corrections, three additional regressions and this
  validation record (the Git history identifies its exact hash).

Coordinator ticket status is not edited from this project session. No personal
Windows/WSL census, Windows deployment, upstream execution, push, or remote
service connection was performed. Ticket 05 can use the existing CLI/API
interfaces above; it must supply its own explicitly bounded evidence corpus,
common absolute window and established relocation provenance. Missing evidence
still prevents confident unused classifications.
