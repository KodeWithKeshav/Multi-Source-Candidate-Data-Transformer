"""Ingest & Sniff — detect source types and wrap raw data.

Given file paths, URLs, or usernames, this module detects the source
type by extension + lightweight content sniffing, then wraps each as
a ``SourceDocument`` with a SHA-256 content hash for traceability.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from pathlib import Path

from transformer.models import SourceDocument, SourceType

logger = logging.getLogger(__name__)


def _sha256(data: str | bytes) -> str:
    """Return the hex SHA-256 digest of *data*."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------
# Content-sniffing helpers
# ------------------------------------------------------------------

def _looks_like_csv(text: str) -> bool:
    """Heuristic: does the text look like CSV with a header row?"""
    try:
        sample = text[:4096]
        reader = csv.reader(io.StringIO(sample))
        header = next(reader, None)
        if header and len(header) >= 2:
            # Check for at least one known recruiter-CSV column name
            known = {"name", "email", "phone", "current_company", "title"}
            if known & {h.strip().lower() for h in header}:
                return True
            # Fallback: multiple comma-separated columns looks CSV-ish
            return len(header) >= 3
    except Exception:
        pass
    return False


def _looks_like_json(text: str) -> bool:
    """Heuristic: does the text parse as JSON?"""
    stripped = text.strip()
    if stripped and stripped[0] in ("{", "["):
        try:
            json.loads(stripped)
            return True
        except (json.JSONDecodeError, ValueError):
            pass
    return False


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def detect_source_type(path: str) -> SourceType:
    """Detect the source type of a file by extension + content sniffing.

    Rules:
        1. ``.csv`` → CSV (confirmed by header sniff)
        2. ``.json`` → ATS JSON (confirmed by JSON parse)
        3. ``.txt`` → Recruiter notes
        4. If extension is ambiguous, fall back to content sniffing.

    Raises ``ValueError`` for unrecognizable files.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    # Read a small sample for sniffing
    try:
        sample = p.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        raise ValueError(f"Cannot read file for source detection: {path}")

    # Extension-first, then content-sniff to confirm
    if suffix == ".csv":
        return SourceType.CSV
    if suffix == ".json":
        return SourceType.ATS
    if suffix == ".txt":
        # Could be notes OR a list of GitHub usernames — callers
        # disambiguate via CLI flag, so default to NOTES here.
        return SourceType.NOTES

    # Ambiguous extension — fall back to pure content sniffing
    if _looks_like_csv(sample):
        return SourceType.CSV
    if _looks_like_json(sample):
        return SourceType.ATS

    return SourceType.NOTES  # conservative default for plain text


def ingest_file(path: str, forced_type: SourceType | None = None) -> SourceDocument:
    """Read a single file and wrap it as a ``SourceDocument``.

    Args:
        path: Filesystem path to the source file.
        forced_type: If provided, skip detection and use this type.

    Returns:
        A ``SourceDocument`` ready for an adapter.
    """
    p = Path(path)
    raw_bytes = p.read_bytes()
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    content_hash = _sha256(raw_bytes)

    source_type = forced_type or detect_source_type(path)

    # For JSON sources, parse into a Python object so adapters don't
    # have to re-parse.
    if source_type == SourceType.ATS:
        try:
            raw: str | list | dict = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse JSON from %s: %s", path, exc)
            raw = raw_text
    else:
        raw = raw_text

    return SourceDocument(
        raw=raw,
        source_type=source_type,
        source_id=str(p.name),
        content_hash=content_hash,
    )


def ingest_github_usernames(path: str) -> list[str]:
    """Read a text file containing one GitHub username per line.

    Blank lines and lines starting with ``#`` are skipped.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    usernames: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            # Support full URLs: extract username from
            # ``https://github.com/<username>``
            if "github.com/" in line:
                line = line.rstrip("/").rsplit("/", 1)[-1]
            usernames.append(line)
    return usernames


def make_github_source_document(username: str, profile_data: dict, repos_data: list) -> SourceDocument:
    """Create a ``SourceDocument`` for a GitHub user from API responses."""
    combined = json.dumps({"profile": profile_data, "repos": repos_data}, sort_keys=True)
    return SourceDocument(
        raw={"profile": profile_data, "repos": repos_data},
        source_type=SourceType.GITHUB,
        source_id=f"github:{username}",
        content_hash=_sha256(combined),
    )
