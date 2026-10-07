"""Shared helpers for trace adapters. Deterministic, dependency free."""

from __future__ import annotations

import datetime as dt
import hashlib
import ntpath
import posixpath
import re

from drskill.text import one_line

EXCERPT_LIMIT = 200

_SKILL_MD = re.compile(r"(?<![A-Za-z0-9._${}-])([A-Za-z0-9._-]+)[\\/]SKILL\.md")
_SINCE_DAYS = re.compile(r"(\d+)d")


def excerpt(s: str | None) -> str | None:
    if s is None:
        return None
    return one_line(s, EXCERPT_LIMIT)


def skill_md_names(text: str) -> list[str]:
    """Skill directory names from SKILL.md paths, first-seen order, deduped."""
    seen: list[str] = []
    for m in _SKILL_MD.finditer(text):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def parse_since(spec: str, now: dt.datetime) -> dt.datetime:
    """'7d' / '30d' / '2026-06-01' -> an aware UTC cutoff. Raises ValueError."""
    m = _SINCE_DAYS.fullmatch(spec)
    if m:
        return now - dt.timedelta(days=int(m.group(1)))
    d = dt.date.fromisoformat(spec)
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)


def parse_ts(value: object) -> dt.datetime | None:
    """ISO string (Z suffix fine) -> aware UTC datetime, else None."""
    if not isinstance(value, str):
        return None
    try:
        ts = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc)


def munge_path(p: str) -> str:
    """A cwd the way Claude Code names its per-project trace directory."""
    return re.sub(r"[/.]", "-", p)


def resolve_read_path(requested: str, cwd: str | None) -> tuple[str | None, list[str]]:
    """Lexical recorded-namespace normalization; never consult the host filesystem."""
    qualifications: list[str] = []
    windows_qualification = [
        "Windows lexical namespace; separators and drive letter normalized; case-sensitive matching because resource case policy is unknown",
    ]

    def windows_absolute(value: str) -> bool:
        drive, tail = ntpath.splitdrive(value)
        if re.fullmatch(r"[A-Za-z]:", drive):
            return tail.startswith(("/", "\\"))
        # Ordinary UNC only; device/extended namespaces are deliberately unsupported.
        parts = drive.replace("\\", "/").split("/")
        return (len(parts) == 4 and parts[:2] == ["", ""]
                and all(parts[2:]) and parts[2] not in ("?", "."))

    def windows_normalize(value: str) -> str:
        normalized = ntpath.normpath(value).replace("\\", "/")
        if re.match(r"^[A-Za-z]:", normalized):
            normalized = normalized[0].upper() + normalized[1:]
        return normalized

    if requested.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        return None, ["Unresolved Windows device or extended namespace"]
    if windows_absolute(requested):
        return windows_normalize(requested), windows_qualification
    if isinstance(cwd, str) and windows_absolute(cwd):
        # Root-relative requests lack a drive/share; POSIX-looking absolute paths
        # could instead be WSL aliases. Neither is inferred from a Windows cwd.
        if requested.startswith(("/", "\\")):
            return None, ["Unresolved rooted path: ambiguous Windows/POSIX namespace"]
        if not (requested.startswith(("~", "@"))
                or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", requested)):
            return windows_normalize(ntpath.join(cwd, requested)), windows_qualification
    if (requested.startswith(("~", "@"))
            or re.match(r"^[A-Za-z]:", requested)
            or "\\" in requested
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", requested)):
        qualifications.append("Unresolved path alias or non-POSIX namespace")
        return None, qualifications
    if requested.startswith("/"):
        return posixpath.normpath(requested), qualifications
    if isinstance(cwd, str) and cwd.startswith("/"):
        return posixpath.normpath(posixpath.join(cwd, requested)), qualifications
    qualifications.append("Relative path unresolved: missing absolute session cwd")
    return None, qualifications


def combined_use_id(session_id: str, turn_id: str, resolved_path: str) -> str:
    return hashlib.sha256(
        f"{session_id}\n{turn_id}\n{resolved_path}".encode("utf-8")
    ).hexdigest()
