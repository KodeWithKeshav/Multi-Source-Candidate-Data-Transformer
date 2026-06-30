"""CSV adapter — parse a recruiter CSV into FieldObservations.

Expected columns: ``name, email, phone, current_company, title``.
Malformed rows (wrong column count, stray delimiters) are **skipped**
with a logged warning — they never crash the run.
"""

from __future__ import annotations

import csv
import io
import logging

from transformer.adapters.base import BaseAdapter
from transformer.models import (
    ExtractionMethod,
    FieldObservation,
    SourceDocument,
    SourceType,
)

logger = logging.getLogger(__name__)

# Mapping from CSV column names (lowercased) to canonical field paths.
COLUMN_MAP: dict[str, str] = {
    "name": "full_name",
    "email": "emails",
    "phone": "phones",
    "current_company": "experience[0].company",
    "title": "experience[0].title",
}


class CsvAdapter(BaseAdapter):
    """Adapter for recruiter CSV files."""

    def adapt(self, doc: SourceDocument) -> list[FieldObservation]:
        """Parse CSV rows into field observations.

        Each row becomes a cluster of observations sharing the same
        ``candidate_key_hint`` (the email, when available, else the name).
        """
        observations: list[FieldObservation] = []
        raw_text = doc.raw if isinstance(doc.raw, str) else str(doc.raw)

        try:
            reader = csv.DictReader(io.StringIO(raw_text))
        except Exception as exc:
            logger.warning("Cannot parse CSV %s: %s", doc.source_id, exc)
            return observations

        for row_num, row in enumerate(reader, start=2):  # row 1 = header
            try:
                self._process_row(row, row_num, doc, observations)
            except Exception as exc:
                logger.warning(
                    "Skipping malformed CSV row %d in %s: %s",
                    row_num, doc.source_id, exc,
                )
                continue

        return observations

    # ------------------------------------------------------------------ #

    @staticmethod
    def _process_row(
        row: dict[str, str | None],
        row_num: int,
        doc: SourceDocument,
        observations: list[FieldObservation],
    ) -> None:
        """Convert a single CSV row into observations."""
        # Determine the candidate key (email preferred, name fallback).
        email = (row.get("email") or "").strip()
        name = (row.get("name") or "").strip()
        key_hint = email if email else name

        if not key_hint:
            logger.warning(
                "Row %d in %s has no name or email — skipping.",
                row_num, doc.source_id,
            )
            return

        for csv_col, canonical_path in COLUMN_MAP.items():
            value = row.get(csv_col)
            if value is not None:
                value = value.strip()
            if not value:
                continue  # absent / empty — no observation

            observations.append(
                FieldObservation(
                    path=canonical_path,
                    value=value,
                    source=SourceType.CSV,
                    method=ExtractionMethod.DIRECT,
                    raw_span=value,
                    candidate_key_hint=key_hint,
                )
            )
