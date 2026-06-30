"""Assemble — build a canonical CandidateProfile from merged data.

This module constructs the ``CandidateProfile`` Pydantic model from
the merged field data produced by ``merge.py``. It populates the
provenance list from the merge log.

Invariant: **no values are invented**. A field with no evidence
remains ``None`` / empty list, confidence ``0.0``.
"""

from __future__ import annotations

import logging
from typing import Any

from transformer.merge import MergedField, compute_overall_confidence
from transformer.schema import CandidateProfile

logger = logging.getLogger(__name__)


def _get(merged: dict[str, MergedField], path: str, default: Any = None) -> Any:
    """Get a merged field's value, or *default* if absent."""
    field = merged.get(path)
    if field is None:
        return default
    return field.value if field.value is not None else default


def _get_list(merged: dict[str, MergedField], path: str) -> list:
    """Get a list-valued merged field, ensuring the result is a list."""
    val = _get(merged, path, [])
    if isinstance(val, list):
        return val
    return [val]


def assemble_profile(
    candidate_id: str,
    merged: dict[str, MergedField],
    provenance_log: list[dict],
) -> CandidateProfile:
    """Build a canonical ``CandidateProfile`` from merged field data.

    Args:
        candidate_id: The resolved candidate identifier.
        merged: Dict of canonical field path → MergedField.
        provenance_log: Full provenance log from the merge stage.

    Returns:
        A fully-assembled ``CandidateProfile`` — the single internal
        source of truth for this candidate.
    """
    # --- Full name ---
    full_name = _get(merged, "full_name", "Unknown")

    # --- Emails & phones (list fields) ---
    emails = _get_list(merged, "emails")
    phones = _get_list(merged, "phones")

    # --- Location ---
    location: dict[str, str | None] = {}
    city = _get(merged, "location.city")
    region = _get(merged, "location.region")
    country = _get(merged, "location.country")
    if city or region or country:
        location = {"city": city, "region": region, "country": country}

    # --- Links ---
    links: dict[str, Any] = {}
    linkedin = _get(merged, "links.linkedin")
    github = _get(merged, "links.github")
    portfolio = _get(merged, "links.portfolio")
    other = _get_list(merged, "links.other")
    if linkedin:
        links["linkedin"] = linkedin
    if github:
        links["github"] = github
    if portfolio:
        links["portfolio"] = portfolio
    if other:
        links["other"] = other

    # --- Headline ---
    headline = _get(merged, "headline")

    # --- Years of experience ---
    years_experience = _get(merged, "years_experience")
    if years_experience is not None:
        try:
            years_experience = float(years_experience)
        except (ValueError, TypeError):
            years_experience = None

    # --- Skills (list of dicts with name + confidence + sources) ---
    raw_skills = _get_list(merged, "skills")
    skills_field = merged.get("skills")
    skills: list[dict] = []
    seen_skills: set[str] = set()
    for s in raw_skills:
        s_name = str(s).strip()
        s_lower = s_name.lower()
        if s_lower in seen_skills:
            continue
        seen_skills.add(s_lower)
        skill_entry: dict[str, Any] = {
            "name": s_name,
            "confidence": skills_field.confidence if skills_field else 0.0,
            "sources": skills_field.agreeing_sources if skills_field else [],
        }
        skills.append(skill_entry)

    # --- Experience ---
    experience: list[dict] = []
    company = _get(merged, "experience[0].company")
    title = _get(merged, "experience[0].title")
    start = _get(merged, "experience[0].start")
    end = _get(merged, "experience[0].end")
    summary = _get(merged, "experience[0].summary")
    if company or title:
        experience.append({
            "company": company,
            "title": title,
            "start": start,
            "end": end,
            "summary": summary,
        })

    # --- Education ---
    education: list[dict] = []
    institution = _get(merged, "education[0].institution")
    degree = _get(merged, "education[0].degree")
    field = _get(merged, "education[0].field")
    end_year = _get(merged, "education[0].end_year")
    if institution or degree:
        education.append({
            "institution": institution,
            "degree": degree,
            "field": field,
            "end_year": end_year,
        })

    # --- Confidence ---
    overall_confidence = compute_overall_confidence(merged)

    # --- Field confidences ---
    field_confidences = {
        path: mf.confidence for path, mf in merged.items()
    }

    return CandidateProfile(
        candidate_id=candidate_id,
        full_name=full_name,
        emails=emails,
        phones=phones,
        location=location,
        links=links,
        headline=headline,
        years_experience=years_experience,
        skills=skills,
        experience=experience,
        education=education,
        provenance=provenance_log,
        overall_confidence=overall_confidence,
        field_confidences=field_confidences,
    )
