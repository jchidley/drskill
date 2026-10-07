# Pi nested-read extraction handoff (ticket 02)

This is a qualified evidence seam for ticket 03, **not audit/report integration**.
There is no recorder, storage layer, JavaScript-source parser, or display-preview
fallback. Existing native-read and expanded-wrapper invocation detectors remain.

## API and scope

```python
from pathlib import Path
from drskill.traces import pi
from drskill.traces.pipeline import extract_pi_nested_corpus

single = pi.extract(Path("session.jsonl"))  # PiExtractResult
corpus = extract_pi_nested_corpus([Path("parent.jsonl"), Path("child.jsonl")])
```

Both expose `nested_reads: list[NestedRead]` and
`nested_diagnostics: list[NestedDiagnostic]`. The single-file API also preserves
the existing `invocations` and `recognized` outputs. The corpus seam deliberately
does not invoke native/wrapper detectors, the audit cache, or user-facing counts.
Ticket 03 must consume the separate evidence, not treat it as direct assistant
tool calls or silently lose it through the current invocation-only cache.

Scope is **all raw branches in explicitly supplied physical logs**. Result entry
ID, its retained `parentId`, session ID, source file and line preserve branch
provenance. Native and nested single-file evidence share one byte snapshot, even if a live
file grows during extraction. This API does not select a branch leaf or infer missing ancestry from
linear order. It does not discover children from launch acknowledgements or open
unrequested parent files. Include the expected child path explicitly; an absent
file yields `missing-session`. Unknown/unprovided child logs are missing coverage,
not proof of no child execution.

### Positive evidence and identity

A finalized `type: message`, `role: toolResult`, `toolName: codemode` entry must
retain `message.nestedCalls.calls[]`. Only a known `read` row with `status: ok`,
a nonempty stable call ID and structured nonempty `arguments.path` yields a
successful read. Stable session/result IDs are also required; duplicate
result/call identities are rejected rather than guessed.

Each row contains:

| Field | Meaning |
| --- | --- |
| `occurrence` | (session header ID, result entry ID, nested call ID); not globally unique call IDs |
| `result_record_time` | Retained valid ISO outer-entry timestamp, or null with a diagnostic; **not** nested-call start time |
| `result_parent_id` | Retained parent entry ID, when present |
| `requested_path` | Original structured spelling, including redundant dot components |
| `resolved_path` | Lexical POSIX path normalized against header cwd, or null for unresolved aliases/namespaces/cwd |
| `source_file`, `source_line`, `source_sha256` | Physical snapshot provenance; hash is of bytes actually parsed |
| `provenance` | Optional sanitized fixture source locator (`evidenceSource` in projections), not authenticated runtime metadata |
| `qualifications` | Effective-path, historical-resource, partial-read and timestamp limits |
| `inheritance` | unresolved, independent, or inherited |
| `execution_owner` | Verified owning occurrence, or null when unresolved |

This establishes a finalized pipeline outcome for the **recorded request**,
not independently attested OS access. Hooks can transform paths and outcomes.
Lexical normalization does not establish historical realpath, immutable resource
identity, symlink targets, file hashes or full-file coverage. Offset/limit is
explicitly marked partial. Tilde, @ aliases, URI/scheme and Windows namespaces
are unresolved rather than mapped through the analyzer's environment.
A read does not prove invocation intent, following instructions or task completion.
Resource membership and declared supporting relationships remain ticket 03 work;
the extractor does not classify every markdown read as a skill invocation.

Outer success cannot certify a failed row; outer failure cannot erase an earlier
`ok` row. Display-only `details.calls[].args` never supplies a missing structured
path. A complete individual row remains positive when overall coverage is
incomplete.

### Corpus ownership

For a child with `parentSession`, follow only supplied ancestor files and compare
the matching result entry ID and **entire result message payload**, including
nested-call identity. Matching inherited results retain the ancestor execution
owner and separate physical occurrences. An inherited relative request uses the
verified owner's cwd, not a potentially changed child cwd.

Missing parents, ambiguous session identities, invalid ancestor evidence, cycles
and conflicting payloads leave ownership unresolved with `ancestry-*`
diagnostics. Equal IDs/paths/payloads in unrelated sessions are never deduplicated.
A parent link alone is insufficient. Count resolved execution owners once;
report unresolved occurrences separately, not as definitely new executions.
Single-file extraction leaves ownership unresolved until corpus reconciliation.

### Coverage

Diagnostics include missing structured metadata, malformed records, unsuccessful
or unfinished rows, missing identities/arguments, missing result times, incomplete
coverage and unresolved ancestry. The inspected recorder retains at most
**256 calls**, **8 KiB arguments per call**, **32 KiB arguments per result** and
500 error characters. Arguments may be omitted with `argumentsBytes`, excess
calls dropped, and `unfinished` rows retained. Missing arguments are not
reconstructed. Complete retained rows remain usable despite those losses.

A missing field alone cannot prove no nested use: old runtimes, interruption,
partial exports, modified records and calls never made can all leave no field.
Capability is established from actual retained structured records, **not**
JSONL format version 3 or the root Pi 0.85.1 development dependency. No minimum
Pi release introducing this evidence was established.

## Runnable demonstration and fixtures

From the drskill root:

```sh
uv run python scripts/pi_nested_demo.py
uv run pytest tests/test_traces_pi_nested.py tests/test_traces_pi.py tests/test_traces_pipeline.py
```

The demo constructs temporary JSONL projections from
`tests/fixtures/pi-nested/observed-execution.json` and
`observed-session-boundaries.json`. These are sanitized **observed Pi 1.0.4**
metadata copied unchanged from ticket 01 (commits `2f96958c`, `6dc76dba`) in
agent-skills. Original snapshot hashes and source entry locators are retained.
IDs, timestamps, paths and errors are sanitized; no raw instruction/file/user
bodies or secrets are included. Parent path is remapped only to connect the
temporary projections; this is not a replay of the original sessions.

The demonstration also includes an explicitly labelled **synthetic,
source-qualified** 256-row incomplete record with omitted >8 KiB arguments,
per-call argument loss and one complete partial read. It does not claim to
execute recorder overflow. Expected summary:

```json
{
  "successful_read_occurrences": 9,
  "resolved_executions": 8,
  "inherited_occurrences": 1,
  "unresolved_occurrences": 0
}
```

Eight occurrences are observed projections (five main, two inherited-boundary,
one standalone child); one is synthetic. Missing standalone result time is
retained as null with a diagnostic. Output includes full successful rows,
provenance, qualifications, ownership and diagnostics. Temporary source paths
vary; summary and occurrence IDs are stable. The tests separately demonstrate 32 KiB aggregate argument loss and inherited
path qualifications, as well as missing child/parent files, conflicting ancestry, cycles, unrelated equal IDs,
failed/unfinished/malformed reads, duplicate identity, aliases, preview-only
records and recorder bounds. Synthetic cases are labelled as such in test names.

## Implementation validation

Task-start review baseline: `8ba75d732357800554b4ddc35a0871b0a516b99a`,
branch `local/pi-support`, clean at start.

- Initial focused public discovery/extraction/pipeline tests: **123 passed**.
- Initial `uv run pytest`: **1191 passed, 7 failed**. Two deep tests require missing
  `litellm`; five MCP connect tests require missing `mcp` (optional extras).
  This is **not** a green full-suite gate. No dependencies or extras were installed.
  Initial local output: `/tmp/drskill-ticket02-pytest.log`.
- Re-ran the full suite after the inherited-path fix and snapshot refactor:
  **1193 passed, the same 7 failed** for missing optional dependencies.
  Final local output: `/tmp/drskill-ticket02-pytest-final.log`.
- `uv run python scripts/pi_nested_demo.py`: expected 9 occurrences / 8 resolved
  executions / 1 inherited / 0 unresolved; output inspected.
- `uv run python -m compileall -q` on changed trace modules and demo: passed.
  `pyproject.toml` declares pytest but no typechecking or lint gate; syntax
  compilation is not claimed as typechecking.
- `git diff --check`: passed.
- The discovery child ran an intermediate full suite while corpus work was
  incomplete (1184 passed / 13 failed, including six in-progress import errors).
  The final parent run above supersedes that intermediate result.

Ticket completion must be recorded in a separate agent-skills-root session;
this drskill commit does not edit the coordinator ticket or unblock ticket 03
by itself.

## Review follow-up

Standards review of `1ca77f1` found no documented-standard violations and four
judgement-call smells. Renamed the recorder-bounds constant, removed duplicate
JSONL parsing, and replaced positional snapshot tuples with a named internal
dataclass. Kept the small demo/test projection duplication intentionally: sharing
fixture construction would couple the independent regression setup to the demo.

Parent verification found and corrected inherited path qualifications:
the child now receives the verified owner's context and qualifications.
Added separate aggregate-budget and missing-owner-cwd regressions.
Post-follow-up focused tests: **125 passed**; trace-only focused tests after
the snapshot refactor: **62 passed**. The demonstration still returns 9/8/1/0. A fresh Standards follow-up reviewed
`3a32e48` and `8824650`, independently ran all 27 nested tests, and reported
no unresolved Standards findings or regressions. The initial four smell findings
were resolved (three code changes, one justified retention).

Spec review of `1ca77f1` reported two material findings and one minor snapshot
consistency concern, with no scope creep. The material findings were the
aggregate-budget regression gap and inherited-path qualification bug; the
reviewer independently verified both fixes in `3a32e48` / `8824650`.
The remaining minor concern (native and nested detectors reading a live file
separately) was reproduced by a filesystem-boundary regression and corrected:
both now consume the same bytes. Focused tests after that fix: **126 passed**.

## Source evidence and historical qualification

Ticket 01's source-qualified extraction contract is at
`/home/jack/git/agent-skills/.scratch/codemode-skill-usage/evidence/session-evidence.md`.
Recorder source independently inspected in this implementation:
`/home/jack/git/pi-mono/packages/coding-agent/src/core/nested-tool-calls.ts`
(the bounds, pre-pipeline argument snapshot, finalized statuses and completeness).
That is supporting source evidence, not a substitute for retained runtime fields.

Two historical agent-skills snapshots were inspected by metadata only:

| Session ID / header time | Snapshot SHA-256 | Retained evidence |
| --- | --- | --- |
| `01a07b1f-fa04-77e6-af00-198f577763b1` / 2026-09-07T09:08:08.325Z | `75af4d5ba79c46cf38eb7fc6b80b469171107892f61b4459488f1a4e8b4e5dec` | format 3; zero codemode results, zero structured nested records |
| `c6d752f9-a3f3-4bb2-bd76-6b026b9e7cec` / 2026-09-07T09:16:32.550Z | `97030e5330e3d3b728f6542da62cbdaaac0c3d29aaebaa097f4cd7d273e69831` | format 3; zero codemode results, zero structured nested records |

These snapshots lack structured evidence but do **not** demonstrate a historical
codemode result with an omitted field. Their runtime capability and absence of
nested use cannot be established from the format number or missing field.
A bounded scan of the first 60 chronologically named agent-skills logs found no
codemode-result session without structured records; this is not whole-history
coverage. No raw historical sessions were copied into this repository.

## Discovery slice

Pi package discovery now reports unsupported brace/extglob/piped patterns rather
than silent literal missing roots, and stops recursion at package skill leaves.
The adapter remains intentionally limited: all nonempty settings-level skill
filters (including exact paths) are unsupported; project autoload:false deltas
are not resolved. Empty declarations/filters, local directory roots and
environment overrides remain supported. README distinguishes finalized reads,
instruction-delivery wrappers and task completion.
