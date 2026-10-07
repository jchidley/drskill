"""Per-trace-file extraction cache.

Machine state under home/.drskill/cache/audit, never committed: entries hold
excerpts of the user's prompts. One JSON file per trace file, keyed by the
sha256 of the trace's absolute path, invalidated by mtime_ns + size and by
the adapter version.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

from drskill.traces.model import Invocation
from drskill.traces.pi_nested import PiExtractResult

CACHE_VERSION = 3


class TraceCacheEntry(BaseModel):
    cache_version: int = CACHE_VERSION
    pi_evidence: PiExtractResult | None = None
    trace_path: str
    mtime_ns: int
    size: int
    adapter: str
    adapter_version: int
    recognized: int = 0
    invocations: list[Invocation] = Field(default_factory=list)


def audit_cache_dir(home: Path) -> Path:
    return home / ".drskill" / "cache" / "audit"


def entry_key(trace_path: Path) -> str:
    return hashlib.sha256(str(trace_path.resolve()).encode()).hexdigest()


def load_entry(cdir: Path, trace_path: Path) -> TraceCacheEntry | None:
    """The cached entry, or None when absent, corrupt, or stale by mtime/size."""
    p = cdir / f"{entry_key(trace_path)}.json"
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("cache_version") != CACHE_VERSION:
            return None
        entry = TraceCacheEntry.model_validate(payload)
    except (OSError, ValueError):
        return None
    try:
        st = trace_path.stat()
    except OSError:
        return None
    if entry.cache_version != CACHE_VERSION or entry.mtime_ns != st.st_mtime_ns or entry.size != st.st_size:
        return None
    return entry


def store_entry(cdir: Path, entry: TraceCacheEntry) -> None:
    """Best effort: an unwritable cache degrades to re-extraction, never an error."""
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        p = cdir / f"{entry_key(Path(entry.trace_path))}.json"
        p.write_text(entry.model_dump_json(), encoding="utf-8")
    except (OSError, UnicodeError):
        pass


def prune_vanished(cdir: Path, live: set[str]) -> int:
    removed = 0
    for p in sorted(cdir.glob("*.json")) if cdir.is_dir() else []:
        if p.stem not in live:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed
