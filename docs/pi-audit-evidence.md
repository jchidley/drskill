# Pi evidence-aware audit (ticket 03)

Ticket 02's verified handoff in [pi-nested-extraction.md](pi-nested-extraction.md)
satisfies the prerequisite; ticket 03's coordinator wording saying “not yet
complete” is stale. This implementation starts from clean `57ac64f` on the
current branch. Coordinator ticket completion must be recorded separately from
an agent-skills-root session; this change does not edit coordinator tickets.

## Commands and evidence windows

```sh
# Current project, all retained branches in discovered session files
uv run drskill audit --harness pi
# All projects, cached corpus reconciliation, all retained branches
uv run drskill audit --harness pi --global --json
# One supplied physical log; does not open unrequested parents or children
uv run drskill audit --file /path/session.jsonl --harness pi --json
# One raw Pi branch, from the specified leaf through parentId ancestry
uv run drskill audit --file /path/session.jsonl --harness pi --branch ENTRY_ID
# Time filtering uses retained timestamps, not nested-call start times
uv run drskill audit --harness pi --since 30d --json
# Named drilldown retains delivery/read evidence separately
uv run drskill audit implement --harness pi --json
```

Without `--branch`, both corpus and explicit-file reports inspect **all retained
raw branches**. Branch selection requires an explicit Pi file and rejects
missing, duplicate or cyclic ancestry. It does not infer a selected leaf,
interpret compacted model context, or discover children from acknowledgements.
Branch diagnostics remain conservative and are labelled report-wide in named drilldowns: malformed/unavailable records are not
discarded to certify complete branch coverage.

Project scoping uses recorded cwd. Nested rows lacking a result timestamp remain
visible under `--since` with unknown membership in the time window; dated rows
are filtered normally. `--last` selects the newest retained timed observation,
including nested-only sessions. Supplied ancestors are reconciled before these
filters, so owner evidence outside the displayed slice can still establish
inheritance.

## Evidence and matching rules

Machine output retains `invocations` for existing consumers, plus
`nested_reads`, `nested_diagnostics`, `evidence_summary`, `evidence_scope`,
`inspected_files`, `extraction_versions` and `coverage_limits`.

- **Instruction delivery**: an expanded wrapper, not authenticated UI-command
  provenance. Preserve wrapper entry/parent/turn IDs and its physical locator.
- **Skill-file read**: successful native result or finalized structured nested
  `read` outcome. A path-shaped SKILL.md resource label is qualified as such,
  not authenticated historical inventory membership.
- **Declared supporting read**: a unique same-turn wrapper explicitly declares
  the normalized path via a markdown link. Relative links require its explicit
  “References are relative to /absolute/directory” declaration. Chronology,
  basename similarity and arbitrary markdown reads do not establish support.
- **Unattributed read**: positive nested read retained without claiming skill
  intent or an undeclared supporting relationship.

A delivery and skill read merge in the combined observation count **only** with
a unique same-turn wrapper and an exact normalized location/path match. Both
rows, detector provenance and source locators survive. Missing locations,
unresolved namespaces and basename-only matches remain unmerged.
Supporting reads are reported separately, never treated as independent starts.
Combined uses count Pi skill delivery/read observations only (not other harnesses or MCP calls), not intent, following instructions or completion.

Nested physical occurrences, verified distinct execution owners, inherited
occurrences and unresolved occurrences are separate counts. Owner reconciliation
uses supplied parentSession ancestry, entry/call identities and SHA-256 of the
entire retained result message. Equal IDs/paths in unrelated sessions do not
merge. Missing/conflicting ancestry remains unresolved, excluded from distinct
execution and combined-use counts rather than counted as definitely new.
Native details retain the successful result locator as well as the call locator.
Native read executions and expanded delivery observations also retain verified
owners. Fork copies require matching source-call/delivery and result payloads;
they retain physical rows without inflating combined uses. New child read results
remain distinct, and missing/conflicting ancestry is unresolved.

Only structured arguments/outcomes are consumed. No JavaScript, preview, printed
output, shell mention, raw instruction/file-body fallback or recorder is added.
An earlier successful row survives outer failure; failed/unfinished rows remain
diagnostics. Lexical requested paths are not OS-access attestation, realpath,
immutable historical resource identity, full-file coverage or exact call time.

## Cache and coverage

Pi adapter version **11**, audit cache schema **2**, evidence report version **2**.
Incompatible cache entries are re-extracted. Cache retains qualified rows,
diagnostics, session ancestry, entry parents and result payload hashes, not raw
result bodies. Ownership is recomputed over the current supplied corpus on cache
hits: removing a parent cannot leave a stale inherited-execution claim.
The cache remains private local state under `~/.drskill/cache/audit`.

Missing structured fields, recorder truncation, unsuccessful/unfinished reads,
old runtime capability and unprovided child logs remain unknown coverage.
Format 3 and a development dependency version never establish capability.
Even complete retained rows cannot certify whole-workflow coverage; consequently
a report containing Pi coverage limits does **not** confidently classify installed
resources as unused (`unused: null`). Other-harness behavior is preserved.
This intentionally conservative result is not a pruning recommendation.

## Sanitized representative evidence

```sh
uv run python scripts/pi_audit_demo.py
uv run python scripts/pi_audit_demo.py --json
```

The demo audits the ticket 01 observed metadata projections preserved by ticket
02, plus an explicitly labelled source-qualified synthetic recorder-bounds case.
No upstream execution or skill modification is performed. The evidence window
is sanitized `2026-10-07` result-record dates plus one untimed child row;
it is not a historical timestamp claim or complete replay.

Human summary (temporary source paths vary):

```text
Evidence scope: all-retained-branches
Instruction deliveries: 0 · skill-file reads: 5 · declared supporting reads: 0
Nested reads: 9 physical occurrences · 8 distinct executions · 1 inherited · 0 unresolved
Combined observed uses: 4 (not workflow completion)
Coverage: Pi read coverage is unknown outside retained records ...
```

Machine summary:

```json
{
  "instruction_deliveries": 0,
  "skill_file_reads": 5,
  "supporting_reads": 0,
  "nested_read_occurrences": 9,
  "nested_distinct_executions": 8,
  "nested_inherited_occurrences": 1,
  "nested_unresolved_occurrences": 0,
  "combined_observed_uses": 4
}
```

Supporting-looking fixture paths remain unattributed because the sanitized
projection does not retain the corresponding wrapper declarations. The separate
CLI regression adds an explicitly synthetic declared wrapper and verifies
1 delivery + 1 skill read + 1 supporting read = 1 combined observed use, retaining
both wrapper and read locators. Do not relabel missing observed declarations
as established relationships.

Validation, review dispositions and implementation commits are recorded below
after the final gates. Ticket 04 can use these commands/examples but still needs
owner/coordinator verification before its prerequisite is closed.
