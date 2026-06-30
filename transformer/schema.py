"""Canonical CandidateProfile model — the single internal source of truth.

This is the fully-assembled profile that the merge stage produces.
It is **never** sent directly to the output; the projection stage
(project.py) transforms it into the user-requested output shape.
"""

from __future__ import annotations

from pydantic import BaseModel


class CandidateProfile(BaseModel):
    """Canonical, fully-assembled candidate profile.

    Every non-null field traces back to one or more real source
    observations via the ``provenance`` list. The merge stage
    guarantees: no invented values, no guesses. Absent evidence
    → ``None`` / empty list, never a fabricated value.
    """

    candidate_id: str
    full_name: str
    emails: list[str] = []
    phones: list[str] = []                          # E.164 format
    location: dict = {}                              # {city, region, country (ISO-3166 α-2)}
    links: dict = {}                                 # {linkedin, github, portfolio, other: list[str]}
    headline: str | None = None
    years_experience: float | None = None
    skills: list[dict] = []                          # [{name, confidence, sources: [str]}]
    experience: list[dict] = []                      # [{company, title, start, end, summary}]
    education: list[dict] = []                       # [{institution, degree, field, end_year}]
    provenance: list[dict] = []                      # [{field, source, method, value, …}]
    overall_confidence: float = 0.0

    # Per-field confidence map — internal bookkeeping, not part of output schema.
    field_confidences: dict[str, float] = {}
