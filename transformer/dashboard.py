"""Quality Dashboard — compile aggregate batch-level metrics.

Produces a structured summary of the transformation run:
- Batch summary (counts, warnings)
- Schema coverage (field fill rates, per-field confidence averages)
- Resolution metrics (conflicts, agreements, losing values)

The dashboard JSON is used both as a standalone artifact and as
input to the HTML report generator.
"""

from __future__ import annotations

import logging
from typing import Any

from transformer.schema import CandidateProfile

logger = logging.getLogger(__name__)

# Core canonical fields to measure coverage against.
CORE_FIELDS = [
    "full_name", "emails", "phones", "location", "links",
    "headline", "years_experience", "skills", "experience", "education",
]


def compile_dashboard(
    profiles: list[CandidateProfile],
    total_observations: int,
    sources_used: set[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Compile the Quality Dashboard for a batch of candidate profiles.

    Args:
        profiles: List of assembled CandidateProfile objects.
        total_observations: Total number of FieldObservation objects ingested.
        sources_used: Set of source type names that contributed.
        warnings: Pipeline warnings collected during the run.

    Returns:
        A structured dict containing batch_summary, schema_coverage,
        and resolution_metrics.
    """
    total_merged = len(profiles)

    # ---- 1. Field fill rate ----
    total_slots = total_merged * len(CORE_FIELDS)
    populated_count = 0

    for profile in profiles:
        for field in CORE_FIELDS:
            val = getattr(profile, field, None)
            if val is not None and val != [] and val != {} and val != "":
                populated_count += 1

    fill_pct = (populated_count / total_slots * 100.0) if total_slots > 0 else 0.0

    # ---- 2. Average confidence per canonical field ----
    field_confs: dict[str, list[float]] = {f: [] for f in CORE_FIELDS}
    for profile in profiles:
        for field in CORE_FIELDS:
            conf = profile.field_confidences.get(field)
            if conf is not None and conf > 0:
                field_confs[field].append(conf)

    avg_confidence_per_field: dict[str, float] = {}
    all_confs: list[float] = []
    for field, confs in field_confs.items():
        if confs:
            avg = sum(confs) / len(confs)
            avg_confidence_per_field[field] = round(avg, 4)
            all_confs.extend(confs)
        else:
            avg_confidence_per_field[field] = 0.0

    avg_confidence_batch = round(
        sum(all_confs) / len(all_confs), 4
    ) if all_confs else 0.0

    # ---- 3. Resolution metrics from provenance ----
    total_conflicts = 0
    total_agreements = 0
    total_losing_values = 0

    for profile in profiles:
        for entry in profile.provenance:
            status = entry.get("status", "")
            if status == "losing":
                total_conflicts += 1
                total_losing_values += 1
            elif status == "agreeing":
                total_agreements += 1

    dashboard: dict[str, Any] = {
        "batch_summary": {
            "total_candidates_produced": total_merged,
            "total_observations_ingested": total_observations,
            "sources_used": sorted(sources_used),
            "warnings_count": len(warnings),
            "warnings": warnings,
        },
        "schema_coverage": {
            "fields_populated_pct": round(fill_pct, 2),
            "fields_missing_pct": round(100.0 - fill_pct, 2),
            "average_confidence_across_batch": avg_confidence_batch,
            "average_confidence_per_field": avg_confidence_per_field,
        },
        "resolution_metrics": {
            "total_conflicts": total_conflicts,
            "total_agreements": total_agreements,
            "total_losing_values": total_losing_values,
        },
    }

    return dashboard
