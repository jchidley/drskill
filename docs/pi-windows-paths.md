# Recorded Windows read paths (cross-OS ticket 01)

Implementation repository: drskill, branch `local/pi-support`; agreed review
baseline: `cb0cec14fdd72f2166a7c526e34f0b9eacbef72c`. The originating ticket is
`/home/jack/git/agent-skills/.scratch/cross-os-skill-usage/issues/01-resolve-windows-read-paths.md`.
Coordinator completion is recorded separately from an agent-skills-root session.
No Windows installation, inventory, history, skill selection or trust is changed.

## Path and matching contract

Pi extraction **12**, cache schema **2**, evidence report **3**. Pi's adapter
version invalidates incompatible extraction entries, including their cached
`pi_evidence`; the cache shape is unchanged. Both human and machine reports
retain version and namespace qualifications. Original requested spelling,
occurrence identity, source locators/hash/provenance and result-record timestamps
are preserved. Native detection and successful-result certification are unchanged.

The resolver uses Python's standard-library `ntpath.splitdrive`, `join` and
`normpath` for Windows semantics, never host `Path.resolve`, `abspath` or
`realpath` for a recorded resource. Inspection of the uv-managed CPython 3.13.7
`ntpath.py` confirmed its distinctions between drive-absolute, drive-relative,
root-relative and UNC paths and its lexical dot-component handling.
Reference: [Python ntpath/path documentation](https://docs.python.org/3/library/os.path.html).

| Recorded request | Policy |
| --- | --- |
| `C:\skills\example\.\SKILL.md` or `c:/skills/example/SKILL.md` | `C:/skills/example/SKILL.md` |
| `skills\example\SKILL.md` with cwd `D:\Work` | `D:/Work/skills/example/SKILL.md` |
| `\\server\share\skills\example\SKILL.md` | `//server/share/skills/example/SKILL.md` |
| Relative request with an absolute ordinary UNC cwd | Normalize within that recorded share |
| `C:skills\example\SKILL.md` | Unresolved; drive-relative working directory not recorded |
| `\skills\example\SKILL.md`, or `/mnt/c/...` with a Windows cwd | Unresolved rooted/cross-namespace ambiguity |
| `\\?\...`, `\\.\...`, aliases such as `~`, `@`, URI schemes | Unresolved; unsupported namespace |
| Backslash-relative request with POSIX/missing cwd | Unresolved; no namespace translation guessed |
| Ordinary POSIX request with POSIX cwd, or absolute POSIX request without Windows cwd | Existing POSIX normalization |

Canonical Windows paths use forward separators and uppercase drive letters.
UNC share roots normalize with or without a trailing separator to the same
`//server/share` spelling; drive roots retain `C:/` (never the drive-relative
`C:`). Server/share/component spelling is otherwise preserved. Matching is **exact and
case-sensitive**: recorded namespace alone cannot establish the case policy of
a Windows directory or remote UNC resource. Do not lowercase all resources,
equate basenames, strip trailing dots/spaces, resolve symlinks or infer
`C:/...` equals `/mnt/c/...`. A case mismatch deliberately prevents a
declared-support relationship or delivery/read merge. This is conservative
under-attribution, not a claim that Windows universally distinguishes case.

The same resolver applies to wrapper locations, native/nested read requests
and explicit markdown supporting links. Relative supporting links require the
wrapper's explicit `References are relative to <absolute directory>` declaration.
Both slash spellings and drive/UNC declarations are accepted. Successful nested
`SKILL.md` reads receive the existing qualified resource label; uniquely
declared same-turn support receives the wrapper skill name. The same-turn,
exact-path matching rule combines delivery/native/nested skill observations
without discarding the separate evidence rows. Lowercase `skill.md` does not
automatically become a skill label.

Lexical normalization is not proof of actual OS access, immutable file identity,
historical inventory membership, full-file loading or workflow completion.
Partial reads retain offset/limit qualifications. Failed/unfinished reads never
become positive evidence. Verified inherited occurrences use their owner's
recorded path context. Missing/conflicting ancestry remains unresolved.
Windows `parentSession` locators are **not** translated to WSL paths here;
cross-location corpus reconciliation belongs to ticket 04.

## Public regressions and commands

Agreed seams: `pi.extract(Path)`, public audit pipeline/cache behavior and audit
CLI JSON/human output. `tests/test_traces_windows_paths.py` covers drive/UNC and
recorded-relative requests, unsupported/ambiguous namespaces, retained metadata,
Windows wrapper/native/nested attribution and qualified deduplication,
case mismatch, failed/unfinished exclusion, cached inherited owner context,
extraction-11 cache invalidation and mixed POSIX/Windows records.
The previous POSIX-only Windows expectation in the existing extraction test is
updated; other extraction, native-read, audit, cache and report regressions remain.

Run from `/home/jack/git/drskill`:

```sh
uv run pytest tests/test_traces_windows_paths.py -q
uv run pytest tests/test_traces_*.py tests/test_cli_audit.py -q
uv run python -m compileall -q src/drskill/traces scripts/pi_windows_reaudit.py
git diff --check
# Full declared test suite (optional dependencies may be absent):
uv run pytest -q
```

No typechecker or lint gate is declared in `pyproject.toml`; compilation is a
syntax check, not typechecking. This preserves the existing environment without
installing optional dependencies.

## Retained Windows evidence re-audit

The private baseline report has SHA-256
`b6ebb8a37d5c4118b97926113023c534b85fbc1a4111a6a3737eae2a0692c3fa`,
report 2 / extraction 11, 801 inspected files and 77 successful nested reads
with unresolved paths and no classification. Its raw report contains private
bodies; do not copy it into this repository or print it.

`scripts/pi_windows_reaudit.py` calls the existing public audit pipeline over
the explicitly supplied session root, uses a disposable cache, and emits only
aggregate metadata. It compares the baseline's same physical occurrences using
filename plus session/result/call identity, verifies unchanged requested spelling,
result-record time and source line, and fails if an occurrence is absent or
ambiguous. It does not execute resource code or alter Windows installations.
Comparison by physical identity does not grant resource-path or ancestry alias
equivalence. The comparison is to the old report's displayed rows, not a fresh
moving 30-day time-window claim.

Reproduction command (retained private inputs must still exist):

```sh
uv run python scripts/pi_windows_reaudit.py \
  --sessions-root /mnt/c/Users/jackc/.pi/agent/sessions \
  --baseline-report /mnt/c/Users/jackc/AppData/Local/Temp/drskill-audit-6be793c1038a4a3281e77ee78c81f910/report.json
```

Verified aggregate result:

- **801** retained files inspected; **77/77** baseline occurrences matched.
- **77/77** requested paths now resolve lexically.
- **7** become qualified skill-file reads; **0** become declared supporting reads.
- **70** remain unattributed: successful ordinary file reads do not imply skill use.
- All **77** had independent ownership in this supplied corpus.
- Current report **3**, extraction **12**; private source bodies were not emitted.
- The initial two-minute attempt timed out; the same bounded command completed
  with a ten-minute limit (approximately 145 seconds). No fallback extractor used.

## Handoff to tickets 03 and 04

Ticket 03 must obtain concrete approval before changing Windows-native installed
tools and verify their real source/environment identity. This repository commit
is not deployment. Use normal audit interfaces after approved deployment:

```sh
uv run drskill audit --harness pi --global --since 30d --json
uv run drskill audit --file /absolute/path/session.jsonl --harness pi --json
uv run drskill audit example --file /absolute/path/session.jsonl --harness pi
```

Ticket 04 can use the agreed extraction/audit seams and regression fixtures, but
must separately implement a bounded mixed-source corpus/common-window contract.
It must not relabel this per-baseline comparison as an exact common-window report,
nor infer Windows/WSL ancestry or resource equivalence from these normalized paths.

## Validation and task commits

Implementation commits:

- `c3abd7f`: Windows lexical normalization, declared supporting paths,
  extraction/report versions, public regressions and retained-evidence handoff.
- `ff8bdfb`: parent-discovered forward-slash device-cwd fallback fix, with
  red-before-green extraction regressions. Explicit absolute Windows requests
  remain resolvable even when cwd is unsupported; cwd-dependent requests do not.
- `213c2bf`: Spec-review UNC share-root trailing-separator normalization, with a
  red-before-green public audit regression proving delivery/read matching.

Final validation after all behavior commits, from the drskill root:

- `uv run pytest tests/test_traces_*.py tests/test_cli_audit.py -q`:
  **216 passed** (27 Windows-specific cases included).
- `uv run pytest -q`: **1250 passed, 7 failed**, approximately 79 seconds.
  Two failures import absent optional `litellm`; five MCP-connect tests import
  absent optional `mcp`. These are the same seven failures documented at the
  baseline in [pi-audit-evidence.md](pi-audit-evidence.md). This is **not a green
  full-suite gate**. No optional dependencies were installed. Local full log:
  `/tmp/drskill-winpaths-pytest-final.log`.
- `uv run python -m compileall -q src/drskill/traces scripts/pi_windows_reaudit.py`
  and `git diff --check`: passed. No configured typechecker; no typechecking claim.
- Existing `pi_nested_demo.py` and `pi_audit_demo.py --json`: passed; audit demo
  still reports 9 occurrences / 8 executions / 1 inherited / 0 unresolved,
  5 skill reads and 4 combined observations, now extraction 12 / report 3.
- Retained 801-file Windows re-audit above was run at `c3abd7f`. The subsequent
  device-cwd guard and UNC share-root fix do not change its paths: independently
  verified **51** requests are drive-absolute and **26** are relative; all **77**
  have drive-absolute cwd, with **0** UNC requests or device cwds.
  Focused regressions and the final suite cover both corrections. The corpus
  was not needlessly reread after corrections unrelated to its paths.

No ticket record was edited in the coordinator checkout. No changes were pushed,
deployed or installed on Windows. Tickets 03/04 require their own scoped sessions.

## Two-axis review

Both reviewers used fresh standalone `deepseek/deepseek-flash` sessions, a
different model family from the authoring parent; no shared review context.
Fixed point: `cb0cec1`; initial implementation `c3abd7f`, with the parent
correction `ff8bdfb` explicitly inspected by the Standards reviewer.

### Standards

The reviewer found one concrete documented-contract defect and its regression
gap at `c3abd7f`: forward-slash device cwds could reach POSIX fallback.
It verified `ff8bdfb` fixed both. Parent independently reproduced the two failing
public extraction cases before that fix, then ran the focused/final checks above.
The reviewer independently ran all **215** focused tests, compilation and
whitespace checks successfully at corrected HEAD.

Three non-blocking observations: a repeated small alias/scheme predicate
(possible Duplicated Code), the cohesive resolver's growing namespace branches
(possible Divergent Change), and a permissive reference-base regex whose relative
bases nonetheless cannot resolve relative links. No observed wrong output from
these. Local predicates are retained rather than introducing an unneeded
namespace abstraction; absolute-base behavior remains enforced by the resolver.

Standards disposition: concrete defect and regression gap resolved; no remaining
blocking findings. Smell observations are judgment calls, not hard violations.

### Spec

The initial Spec reviewer reported three substantive findings at `c3abd7f`:
the device-cwd fallback (already fixed by `ff8bdfb`), the then-incomplete final
validation/review handoff (filled in here), and inconsistent normalization of UNC
share roots with/without a trailing separator. Parent independently reproduced
the UNC mismatch at the public audit seam, then fixed it in `213c2bf`, retaining
drive-root semantics. It reported one non-blocking reference-base regex/doc
observation shared with Standards; the resolver does not attribute relative
support from a non-absolute declared base. No scope creep was reported.

The reviewer independently ran **215** focused tests and an intermediate full
suite (**1249 passed, 7 missing-extra failures**) before the UNC fix. Parent final
validation supersedes those intermediate counts.

The Spec follow-up independently ran the **27** Windows tests and verified all
four device-cwd spellings, absolute-drive requests with unsupported cwd, UNC root
separator variants and dot components, preserved drive roots, and POSIX behavior.
It found no remaining wrong implementation or missing requirement. Its two
handoff caveats (stale full-suite count and missing final disposition) are now
corrected with the final **1250 passed / 7 failed** result and this paragraph.

Spec disposition: all three substantive findings resolved; no blocking findings
or scope creep. One conservative regex/documentation observation remains, with
no incorrect attribution. Standards had two resolved defect/coverage findings
and three non-blocking observations; Spec had three resolved substantive findings
and one shared non-blocking observation. Neither axis has a remaining blocker.
