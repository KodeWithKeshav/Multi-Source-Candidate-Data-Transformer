"""Recruiter notes adapter — extract structured fields from free-text notes.

Uses **rule-based regex + heuristics only** (no LLM). This is the
lowest-confidence source by design.

Extraction strategies:
    - Email: standard email regex
    - Phone: US-style phone regex
    - Years of experience: ``(\\d+)\\+?\\s*(yrs?|years?)``
    - Skills: matched against a curated alias/lookup table
    - Company: anchor phrases ("currently at", "works at", "is a … at")
    - Title: extracted from the same anchor phrases
    - Location: matched against a curated city/keyword list

NOTE: LinkedIn scraping is explicitly descoped — ToS violation.
NOTE: Resume/PDF parsing is explicitly descoped — complexity out of scope.
"""

from __future__ import annotations

import logging
import re

from transformer.adapters.base import BaseAdapter
from transformer.models import (
    ExtractionMethod,
    FieldObservation,
    SourceDocument,
    SourceType,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Curated lookup tables for heuristic extraction
# ------------------------------------------------------------------

# Skills to scan for (lowercased). We'll match against word boundaries.
KNOWN_SKILLS: set[str] = {
    "python", "java", "javascript", "typescript", "go", "golang", "rust",
    "c++", "c#", "ruby", "php", "swift", "kotlin", "scala", "r",
    "sql", "html", "css", "shell", "bash",
    "react", "angular", "vue", "node", "django", "flask", "fastapi",
    "spring", "rails", "express",
    "docker", "kubernetes", "aws", "gcp", "azure", "terraform",
    "postgres", "postgresql", "mysql", "mongodb", "redis",
    "graphql", "rest", "grpc", "kafka",
    "machine learning", "deep learning", "pytorch", "tensorflow",
    "backend", "frontend", "fullstack", "full-stack", "full stack",
    "devops", "sre", "data engineering", "data science",
    "elixir", "dart", "flutter", "svelte", "next.js", "nuxt",
}

# Simple city/region list for location extraction (lowercased).
KNOWN_LOCATIONS: list[str] = [
    "san francisco", "new york", "los angeles", "chicago", "seattle",
    "austin", "boston", "denver", "portland", "miami", "atlanta",
    "dallas", "houston", "phoenix", "san diego", "san jose",
    "washington dc", "washington d.c.", "philadelphia", "minneapolis",
    "raleigh", "nashville", "salt lake city", "charlotte",
    "london", "berlin", "paris", "amsterdam", "toronto", "vancouver",
    "sydney", "melbourne", "singapore", "tokyo", "bangalore", "bengaluru",
    "hyderabad", "mumbai", "dublin", "tel aviv", "stockholm",
    "sf", "nyc", "la", "bay area", "silicon valley",
]

# Regex patterns
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
PHONE_RE = re.compile(r"(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})")
YEARS_EXP_RE = re.compile(r"(\d+)\+?\s*(?:yrs?|years?)\b", re.IGNORECASE)

# Anchor phrases for company/title extraction.
# Pattern: "(title) at (company)" or "currently at (company) as (title)"
COMPANY_TITLE_PATTERNS: list[re.Pattern[str]] = [
    # "currently at <Company> as <Title>"
    re.compile(
        r"currently\s+at\s+([A-Z][\w&.\-' ]+?)(?:\s+as\s+(?:a\s+|an\s+)?(.+?))?[.,;]",
        re.IGNORECASE,
    ),
    # "works at <Company> as <Title>"
    re.compile(
        r"works?\s+at\s+([A-Z][\w&.\-' ]+?)(?:\s+as\s+(?:a\s+|an\s+)?(.+?))?[.,;]",
        re.IGNORECASE,
    ),
    # "is a <Title> at <Company>"
    re.compile(
        r"is\s+(?:a\s+|an\s+)?(.+?)\s+at\s+([A-Z][\w&.\-' ]+?)[.,;\s]",
        re.IGNORECASE,
    ),
    # "<Title> at <Company>"  (looser, used if none of the above match)
    re.compile(
        r"(?:^|[.,;]\s*)([A-Z][\w ]+?(?:Engineer|Developer|Manager|Lead|Director|VP|Architect|Analyst|Designer|Scientist|Consultant))\s+at\s+([A-Z][\w&.\-' ]+?)[.,;\s]",
        re.IGNORECASE,
    ),
]


class NotesAdapter(BaseAdapter):
    """Adapter for free-text recruiter notes."""

    def adapt(self, doc: SourceDocument) -> list[FieldObservation]:
        """Extract structured observations from free-text notes.

        All extractions use regex/heuristic methods. This is the
        lowest-confidence source by design.
        """
        observations: list[FieldObservation] = []
        text = doc.raw if isinstance(doc.raw, str) else str(doc.raw)

        if not text.strip():
            logger.warning("Notes source %s is empty.", doc.source_id)
            return observations

        key_hint: str | None = None

        # --- Emails ---
        emails = EMAIL_RE.findall(text)
        if emails:
            key_hint = emails[0]
            for email in emails:
                observations.append(
                    FieldObservation(
                        path="emails",
                        value=email,
                        source=SourceType.NOTES,
                        method=ExtractionMethod.REGEX,
                        raw_span=email,
                        candidate_key_hint=key_hint,
                    )
                )

        # --- Phones ---
        phones = PHONE_RE.findall(text)
        for phone in phones:
            observations.append(
                FieldObservation(
                    path="phones",
                    value=phone.strip(),
                    source=SourceType.NOTES,
                    method=ExtractionMethod.REGEX,
                    raw_span=phone.strip(),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Years of experience ---
        yrs_match = YEARS_EXP_RE.search(text)
        if yrs_match:
            years = float(yrs_match.group(1))
            observations.append(
                FieldObservation(
                    path="years_experience",
                    value=years,
                    source=SourceType.NOTES,
                    method=ExtractionMethod.REGEX,
                    raw_span=yrs_match.group(0),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Company & title via anchor phrases ---
        company, title = self._extract_company_title(text)
        if company:
            observations.append(
                FieldObservation(
                    path="experience[0].company",
                    value=company,
                    source=SourceType.NOTES,
                    method=ExtractionMethod.HEURISTIC,
                    raw_span=company,
                    candidate_key_hint=key_hint or company,
                )
            )
        if title:
            observations.append(
                FieldObservation(
                    path="experience[0].title",
                    value=title,
                    source=SourceType.NOTES,
                    method=ExtractionMethod.HEURISTIC,
                    raw_span=title,
                    candidate_key_hint=key_hint,
                )
            )

        # --- Skills ---
        found_skills = self._extract_skills(text)
        if found_skills:
            for skill in found_skills:
                observations.append(
                    FieldObservation(
                        path="skills",
                        value=skill,
                        source=SourceType.NOTES,
                        method=ExtractionMethod.HEURISTIC,
                        raw_span=skill,
                        candidate_key_hint=key_hint,
                    )
                )

        # --- Location ---
        location = self._extract_location(text)
        if location:
            observations.append(
                FieldObservation(
                    path="location.city",
                    value=location,
                    source=SourceType.NOTES,
                    method=ExtractionMethod.HEURISTIC,
                    raw_span=location,
                    candidate_key_hint=key_hint,
                )
            )

        # --- Candidate name (heuristic: "Spoke with <Name>" etc.) ---
        name = self._extract_name(text)
        if name:
            if not key_hint:
                key_hint = name
            observations.append(
                FieldObservation(
                    path="full_name",
                    value=name,
                    source=SourceType.NOTES,
                    method=ExtractionMethod.HEURISTIC,
                    raw_span=name,
                    candidate_key_hint=key_hint,
                )
            )
            # Backfill key_hint on previous observations that had None
            for obs in observations:
                if obs.candidate_key_hint is None:
                    obs.candidate_key_hint = key_hint

        if not observations:
            logger.warning(
                "No structured data could be extracted from notes source %s.",
                doc.source_id,
            )

        return observations

    # ------------------------------------------------------------------ #
    # Private extraction helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_company_title(text: str) -> tuple[str | None, str | None]:
        """Extract company and title from anchor phrases."""
        for pattern in COMPANY_TITLE_PATTERNS:
            m = pattern.search(text)
            if m:
                groups = m.groups()
                if "is a" in pattern.pattern or "is an" in pattern.pattern:
                    # Pattern: "is a <Title> at <Company>"
                    title = groups[0].strip() if groups[0] else None
                    company = groups[1].strip() if len(groups) > 1 and groups[1] else None
                elif pattern.pattern.startswith(r"(?:^|"):
                    # Pattern: "<Title> at <Company>"
                    title = groups[0].strip() if groups[0] else None
                    company = groups[1].strip() if len(groups) > 1 and groups[1] else None
                else:
                    # Pattern: "currently/works at <Company> as <Title>"
                    company = groups[0].strip() if groups[0] else None
                    title = groups[1].strip() if len(groups) > 1 and groups[1] else None
                return company, title
        return None, None

    @staticmethod
    def _extract_skills(text: str) -> list[str]:
        """Match skills from the curated lookup table."""
        text_lower = text.lower()
        found: list[str] = []
        for skill in sorted(KNOWN_SKILLS):  # sorted for determinism
            # Multi-word skills: simple substring match
            if " " in skill or "-" in skill or "." in skill:
                if skill in text_lower:
                    found.append(skill)
            else:
                # Single-word: word boundary match (handles "Go" vs "going")
                # Use \b for most, but special-case short words
                pattern = rf"\b{re.escape(skill)}\b"
                if re.search(pattern, text_lower):
                    found.append(skill)
        return found

    @staticmethod
    def _extract_location(text: str) -> str | None:
        """Match a location from the curated city/keyword list."""
        text_lower = text.lower()
        # Check longest locations first (to prefer "salt lake city" over "lake")
        for loc in sorted(KNOWN_LOCATIONS, key=len, reverse=True):
            if loc in text_lower:
                # Return title-cased
                return loc.title()
        return None

    @staticmethod
    def _extract_name(text: str) -> str | None:
        """Heuristic: extract candidate name from common patterns."""
        patterns = [
            re.compile(r"[Ss]poke\s+with\s+(?:candidate\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"),
            re.compile(r"[Cc]andidate:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"),
            re.compile(r"[Nn]ame:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"),
            re.compile(r"[Ii]nterviewed\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"),
            re.compile(r"[Rr]e:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"),
        ]
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                return m.group(1).strip()
        return None
