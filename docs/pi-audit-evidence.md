# Pi evidence-aware audit (ticket 03)

For the current explicit multi-file corpus, time policy and version contract,
see [Windows-and-WSL audit](pi-cross-os-audit.md). The validation below is the
historical ticket 03 handoff.

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
owners. `native_read_occurrences` and `native_distinct_read_executions` count
reads only; `native_unresolved_occurrences` counts both unresolved native reads
and delivery observations, matching the explicit human label. Fork copies require matching source-call/delivery and result payloads;
they retain physical rows without inflating combined uses. New child read results
remain distinct, and missing/conflicting ancestry is unresolved.

Only structured arguments/outcomes are consumed. No JavaScript, preview, printed
output, shell mention, raw instruction/file-body fallback or recorder is added.
An earlier successful row survives outer failure; failed/unfinished rows remain
diagnostics. Lexical requested paths are not OS-access attestation, realpath,
immutable historical resource identity, full-file coverage or exact call time.

## Cache and coverage

Ticket 01 follow-up baseline: Pi adapter **12**, audit cache schema **2**, evidence report **3**.
The current contract is documented in [pi-cross-os-audit.md](pi-cross-os-audit.md).
[Windows path normalization](pi-windows-paths.md) extends the recorded lexical
namespace without mapping Windows resources or ancestry to WSL. The validation
and review below are the historical ticket 03 baseline (extraction 11/report 2).
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
Native reads: 0 physical occurrences · 0 distinct executions · 0 unresolved native/delivery observations
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
  "native_read_occurrences": 0,
  "native_distinct_read_executions": 0,
  "native_unresolved_occurrences": 0,
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

Ticket 04 can use these commands/examples but still needs owner/coordinator
verification before its prerequisite is closed.

## Validation and implementation handoff

Implementation commits on `local/pi-support`, reviewed against
`57ac64f0bb9fbccde6381c97411370804a1b661c`:

- `7698413`: initial evidence-aware audit integration.
- `0646f9f`: review corrections, shared path/combined policy, and verified
  inherited native/delivery ownership. Pi extraction version is now **11**;
  audit cache schema and evidence report versions remain **2**.

Validation from `/home/jack/git/drskill`:

- Final focused trace adapters, cache, pipeline, reports and audit CLI:
  `uv run pytest tests/test_traces_*.py tests/test_cli_audit.py -q` — **189 passed**.
- After the strict selected-branch ancestry metadata adjustment,
  `uv run pytest tests/test_traces_audit_evidence.py -q` — **15 passed**;
  the subsequent full-suite run includes this change.
- Final parent `uv run pytest` — **1223 passed, 7 failed**. All seven failures
  are the previously recorded unavailable optional dependencies: two deep tests
  import missing `litellm`; five MCP-connect tests import missing `mcp`.
  No extras were installed. This is **not a green full-suite gate**.
  Local log: `/tmp/drskill-ticket03-pytest-final.log`.
- The native implementation child also ran an intermediate full suite before
  final integration: 1209 passed / the same 7 optional-dependency failures.
  The final parent run above supersedes that result.
- `uv run python scripts/pi_audit_demo.py` and `--json`: verified expected
  9 occurrences / 8 executions / 1 inherited / 0 unresolved; all nine rows
  preserve sanitized fixture provenance. Supporting-looking observed paths
  remain unattributed without retained declarations.
- Original extraction demo remains 9/8/1/0.
- `uv run python -m compileall -q src/drskill/traces src/drskill/cli.py scripts/pi_audit_demo.py`
  and `git diff --check`: passed.
- `pyproject.toml` declares pytest but no typechecking or lint gate. Syntax
  compilation is not claimed as typechecking.

Representative local outputs are `/tmp/drskill-ticket03-demo.json` and
`/tmp/drskill-ticket03-demo.txt`. The sanitized examples and exact commands
above are the durable handoff; temporary paths are not stable source identifiers.
No raw private sessions, instruction bodies or secrets were copied, and no
upstream code or skills were executed or modified.

## Two-axis review

Initial **Standards** review of `7698413` reported two behavior concerns and
four minor concerns. The non-Pi combined-count inflation and broadened non-Pi
unused gate were fixed with public regressions. Path normalization and combined
hashing now share policy helpers; native branch checks share an ancestry walker.
The remaining nested turn and selected-branch walkers have different contracts
(raw links only versus legacy native linear context). Summary no longer mutates
input; classification happens in the pipeline. Named drilldown diagnostics are
explicitly labelled report-wide coverage context, not attributed to a skill.

Initial **Spec** review found no material bugs or scope creep and five minor
concerns. Corrected the non-Pi gate and human Pi header (now “evidence rows”,
not “invocations”); filled in this validation handoff. Retained the deliberately
qualified recorded-path resource labels and project-scope diagnostic filtering:
neither authenticates historical resource membership or claims whole-workflow
coverage.

Parent follow-up regressions additionally found and fixed forked delivery/native
combined inflation and duplicate call IDs across tool names. Removed-parent,
relative-file, untimed-window, no-session-reread and duplicate-ancestor cache
regressions pass. Fresh follow-up Standards and Spec reviews of `0646f9f` independently verified
the changes; both used standalone DeepSeek sessions, a different model family
from the parent authoring model.

### Standards follow-up

All seven reviewed prior concerns (including the parent-discovered fork count
bug) were verified resolved. The reviewer independently ran 23 audit/cache tests
and 31 native-Pi tests. Three non-blocking residuals were reported:

- Mixed-run unreadable trace coverage remains conservative. Every mixed report
  with Pi already has unknown whole-workflow coverage; this does not change the
  non-Pi-only behavior covered by its CLI regression.
- A partially matching pair of native source/result IDs yields unresolved
  ownership with a conflict diagnostic. This is intentionally conservative,
  not a claim that a new execution was established.
- A redundant version assignment was removed after review; 33 public
  pipeline/audit regressions and syntax/whitespace checks passed. The full suite
  above predates only this redundant-assignment removal and documentation edits;
  it was not rerun for those non-behavioral changes.

Standards disposition: prior concerns resolved, two conservative edge cases
retained with explicit qualification, no blocking findings.

### Spec follow-up

No material missing requirement, wrong implementation or scope creep. The
reviewer independently ran 54 audit/cache/native tests and verified ancestry,
whole-message payload checks, fork combined counts, removed-parent unknown
ownership, cross-tool duplicate identities and no-session-reread cache behavior.
Two non-blocking residuals: the sample omitted newly added native counts (now
corrected above), and the machine unresolved counter spans both native reads
and delivery observations (now explicitly documented alongside its human label).

Spec disposition: prior concerns resolved, sample drift corrected, count
semantics explicitly qualified, no blocking findings.

Coordinator closure is not performed from this drskill session. Start a separate
Pi session at `/home/jack/git/agent-skills` to record the drskill commit and test
handoff in ticket 03 and independently verify ticket 04 readiness.
