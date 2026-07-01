"""Explain — compile structured per-candidate decision logs.

For each candidate, traces every merge decision back to raw sources,
showing which observations competed, who won, and why. This provides
full explainability for the transformation pipeline.

The decision log is used both as a standalone JSON artifact and as
input to the HTML report generator's Candidate Explorer tab.
"""

from __future__ import annotations

import logging
from typing import Any

from transformer.schema import CandidateProfile

logger = logging.getLogger(__name__)

# Fields that are aggregated (unioned) rather than winner-takes-all.
ARRAY_FIELDS = {"emails", "phones", "skills", "links.other"}


def compile_decision_log(profile: CandidateProfile) -> dict[str, Any]:
    """Compile a structured decision log for a single candidate.

    Traces every field's merge decision back to raw sources, showing
    winners, losers, and agreeing observations.

    Args:
        profile: A fully-assembled CandidateProfile.

    Returns:
        A structured dict with candidate_id and per-field decision traces.
    """
    log: dict[str, Any] = {
        "candidate_id": profile.candidate_id,
        "overall_confidence": profile.overall_confidence,
        "fields": {},
    }

    # Group provenance entries by field path.
    grouped: dict[str, list[dict]] = {}
    for entry in profile.provenance:
        field = entry.get("field", "unknown")
        if field not in grouped:
            grouped[field] = []
        grouped[field].append(entry)

    for field, entries in sorted(grouped.items()):
        is_array = field in ARRAY_FIELDS
        field_confidence = profile.field_confidences.get(field, 0.0)

        # Classify entries by status.
        winner = None
        agreeing: list[dict] = []
        losing: list[dict] = []
        aggregated: list[dict] = []
        failed: list[dict] = []

        for entry in entries:
            status = entry.get("status", "")
            contender = {
                "source": entry.get("source", "unknown"),
                "method": entry.get("method", "unknown"),
                "value": entry.get("value"),
                "raw_span": entry.get("raw_span"),
                "status": status,
            }

            if status == "winner":
                winner = contender
            elif status == "agreeing":
                agreeing.append(contender)
            elif status == "losing":
                losing.append(contender)
            elif status == "aggregated":
                aggregated.append(contender)
            elif status == "normalization_failed":
                failed.append(contender)
            else:
                # Unknown status — still log it.
                losing.append(contender)

        # Build the field decision entry.
        field_decision: dict[str, Any] = {
            "field": field,
            "is_array_field": is_array,
            "final_confidence": field_confidence,
            "candidates_considered": entries,
        }

        if is_array:
            # Array fields — all values are unioned.
            all_values = []
            for e in aggregated:
                v = e.get("value")
                if isinstance(v, list):
                    all_values.extend(v)
                elif v is not None:
                    all_values.append(v)

            # Deduplicate while preserving order.
            seen: set[str] = set()
            unique_values: list[Any] = []
            for v in all_values:
                key = str(v).strip().lower()
                if key not in seen:
                    seen.add(key)
                    unique_values.append(v)

            field_decision["winner_details"] = {
                "resolution": "union",
                "unioned_values": unique_values,
                "source_count": len(aggregated),
                "reason": f"Union + deduplicated array values from {len(aggregated)} source observations.",
            }
        elif winner:
            # Scalar field with a clear winner.
            canonical_value = getattr(profile, field, None)
            # For nested fields, try resolving.
            if canonical_value is None and "." in field:
                parts = field.split(".")
                obj = profile
                for part in parts:
                    if hasattr(obj, part):
                        obj = getattr(obj, part)
                    elif isinstance(obj, dict):
                        obj = obj.get(part)
                    else:
                        obj = None
                        break
                canonical_value = obj

            field_decision["winner_details"] = {
                "resolution": "tier_priority",
                "value": canonical_value,
                "source": winner["source"],
                "method": winner["method"],
                "agreeing_count": len(agreeing),
                "losing_count": len(losing),
                "reason": _build_reason(winner, agreeing, losing),
            }
            field_decision["conflict_detected"] = len(losing) > 0
        else:
            # No clear winner — possibly only normalization-failed entries.
            field_decision["winner_details"] = {
                "resolution": "none",
                "value": None,
                "reason": "No valid observations survived normalization.",
            }

        if failed:
            field_decision["normalization_failures"] = failed

        log["fields"][field] = field_decision

    return log


def _build_reason(
    winner: dict,
    agreeing: list[dict],
    losing: list[dict],
) -> str:
    """Build a human-readable reason string for a merge decision."""
    parts: list[str] = []
    parts.append(
        f"Winner: {winner['source']} (method={winner['method']})."
    )
    if agreeing:
        sources = ", ".join(e["source"] for e in agreeing)
        parts.append(
            f"{len(agreeing)} agreeing source(s): {sources}."
        )
    if losing:
        sources = ", ".join(e["source"] for e in losing)
        values = ", ".join(repr(e["value"]) for e in losing)
        parts.append(
            f"{len(losing)} losing source(s): {sources} "
            f"(rejected values: {values})."
        )
    return " ".join(parts)


def compile_all_decision_logs(
    profiles: list[CandidateProfile],
) -> list[dict[str, Any]]:
    """Compile decision logs for all candidates in a batch.

    Args:
        profiles: List of CandidateProfile objects.

    Returns:
        List of structured decision log dicts, one per candidate.
    """
    return [compile_decision_log(p) for p in profiles]
