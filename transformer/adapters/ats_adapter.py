"""ATS JSON adapter — parse an ATS export into FieldObservations.

ATS field names intentionally **do not** match the canonical schema.
A tolerant alias map handles common renamings; unmapped fields are
ignored (never guessed) and logged at debug level.
"""

from __future__ import annotations

import logging
from typing import Any

from transformer.adapters.base import BaseAdapter
from transformer.models import (
    ExtractionMethod,
    FieldObservation,
    SourceDocument,
    SourceType,
)

logger = logging.getLogger(__name__)

# Tolerant alias map: ATS field name (lowercased) → canonical path.
ALIAS_MAP: dict[str, str] = {
    "candidate_full_name": "full_name",
    "full_name": "full_name",
    "name": "full_name",
    "contact_email": "emails",
    "email": "emails",
    "contact_phone": "phones",
    "phone": "phones",
    "employer": "experience[0].company",
    "current_company": "experience[0].company",
    "company": "experience[0].company",
    "job_title": "experience[0].title",
    "title": "experience[0].title",
    "role": "experience[0].title",
    "skill_tags": "skills",
    "skills": "skills",
    "location": "location.city",
    "city": "location.city",
    "country": "location.country",
    "headline": "headline",
    "bio": "headline",
    "years_experience": "years_experience",
    "experience_years": "years_experience",
    "linkedin": "links.linkedin",
    "linkedin_url": "links.linkedin",
    "github": "links.github",
    "github_url": "links.github",
    "portfolio": "links.portfolio",
    "website": "links.portfolio",
}


class AtsAdapter(BaseAdapter):
    """Adapter for ATS JSON exports."""

    def adapt(self, doc: SourceDocument) -> list[FieldObservation]:
        """Parse ATS JSON records into field observations.

        Expects either a JSON array of candidate objects or a single
        candidate object.
        """
        observations: list[FieldObservation] = []
        raw = doc.raw

        if isinstance(raw, str):
            logger.warning("ATS source %s is plain text, not parsed JSON — skipping.", doc.source_id)
            return observations

        # Normalize to a list of records.
        records: list[dict[str, Any]]
        if isinstance(raw, dict):
            # Could be {"candidates": [...]} or a single candidate object
            if "candidates" in raw:
                records = raw["candidates"]
            else:
                records = [raw]
        elif isinstance(raw, list):
            records = raw
        else:
            logger.warning("Unexpected ATS JSON structure in %s", doc.source_id)
            return observations

        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                logger.warning("ATS record %d in %s is not an object — skipping.", idx, doc.source_id)
                continue
            try:
                self._process_record(record, doc, observations)
            except Exception as exc:
                logger.warning(
                    "Error processing ATS record %d in %s: %s",
                    idx, doc.source_id, exc,
                )

        return observations

    # ------------------------------------------------------------------ #

    @staticmethod
    def _process_record(
        record: dict[str, Any],
        doc: SourceDocument,
        observations: list[FieldObservation],
    ) -> None:
        """Convert a single ATS record into observations via the alias map."""
        # Determine key hint (email preferred).
        email = None
        name = None
        for key, val in record.items():
            alias = ALIAS_MAP.get(key.lower())
            if alias == "emails" and val:
                email = str(val).strip()
            elif alias == "full_name" and val:
                name = str(val).strip()

        key_hint = email or name
        if not key_hint:
            logger.warning("ATS record has no identifiable name/email — skipping.")
            return

        for key, val in record.items():
            canonical = ALIAS_MAP.get(key.lower())
            if canonical is None:
                logger.debug("ATS field %r not in alias map — ignoring.", key)
                continue
            if val is None or (isinstance(val, str) and not val.strip()):
                continue

            # skill_tags may be a list
            if canonical == "skills" and isinstance(val, list):
                observations.append(
                    FieldObservation(
                        path=canonical,
                        value=val,
                        source=SourceType.ATS,
                        method=ExtractionMethod.ALIAS_MAP,
                        raw_span=str(val),
                        candidate_key_hint=key_hint,
                    )
                )
            else:
                observations.append(
                    FieldObservation(
                        path=canonical,
                        value=str(val).strip() if isinstance(val, str) else val,
                        source=SourceType.ATS,
                        method=ExtractionMethod.ALIAS_MAP,
                        raw_span=str(val),
                        candidate_key_hint=key_hint,
                    )
                )
