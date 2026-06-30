"""Merge & Score Confidence — resolve disagreements and compute confidence.

Source reliability tiers (config-overridable weight table):
    ats: 0.9, github: 0.85, csv: 0.7, notes: 0.4

Confidence Formula
==================
For each canonical field, among all surviving (post-normalize) observations:

    field_confidence = base_tier_weight × method_certainty × agreement_boost

where:
    base_tier_weight = tier_weights[winning_source]     (0.0 – 1.0)
    method_certainty = {
        "direct":    1.0,
        "alias_map": 0.95,
        "api":       0.9,
        "regex":     0.7,
        "heuristic": 0.5,
    }
    agreement_boost = 1.0 + 0.1 × (num_agreeing_sources − 1), capped at 1.3

    overall_confidence = weighted mean of all populated field confidences

The highest-tier observation wins. If multiple sources agree on the same
normalized value, the agreement boost raises confidence. If sources
disagree, the winner by tier is kept but **losing values are logged in
provenance** — never silently discarded.

Fields with no evidence → value ``None``, confidence ``0.0``.
Nothing is invented to fill a gap.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from transformer.models import ExtractionMethod, FieldObservation, SourceType

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Default config tables (overridable at runtime)
# ------------------------------------------------------------------

DEFAULT_TIER_WEIGHTS: dict[str, float] = {
    "ats": 0.9,
    "github": 0.85,
    "csv": 0.7,
    "notes": 0.4,
}

METHOD_CERTAINTY: dict[str, float] = {
    "direct": 1.0,
    "alias_map": 0.95,
    "api": 0.9,
    "regex": 0.7,
    "heuristic": 0.5,
}


# ------------------------------------------------------------------
# Merge result types
# ------------------------------------------------------------------

class MergedField:
    """Result of merging observations for a single canonical field."""

    __slots__ = ("path", "value", "confidence", "winning_source", "winning_method",
                 "agreeing_sources", "losing_values")

    def __init__(
        self,
        path: str,
        value: Any,
        confidence: float,
        winning_source: str,
        winning_method: str,
        agreeing_sources: list[str],
        losing_values: list[dict],
    ):
        self.path = path
        self.value = value
        self.confidence = confidence
        self.winning_source = winning_source
        self.winning_method = winning_method
        self.agreeing_sources = agreeing_sources
        self.losing_values = losing_values


# ------------------------------------------------------------------
# Core merge logic
# ------------------------------------------------------------------

def _normalize_for_comparison(value: Any) -> Any:
    """Normalize a value for comparison (case-insensitive string matching)."""
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return sorted(str(v).strip().lower() for v in value)
    return value


def merge_observations(
    observations: list[FieldObservation],
    tier_weights: dict[str, float] | None = None,
) -> tuple[dict[str, MergedField], list[dict]]:
    """Merge a set of observations for a single candidate.

    Args:
        observations: All observations belonging to one candidate cluster.
        tier_weights: Optional override for source tier weights.

    Returns:
        A tuple of:
        - dict mapping canonical field path → ``MergedField``
        - provenance log (list of dicts for every observation, including losers)
    """
    weights = tier_weights or DEFAULT_TIER_WEIGHTS
    provenance: list[dict] = []

    # Group observations by canonical field path.
    by_path: dict[str, list[FieldObservation]] = defaultdict(list)
    for obs in observations:
        if obs.normalization_failed:
            # Keep in provenance but exclude from merge consideration.
            provenance.append({
                "field": obs.path,
                "source": obs.source.value,
                "method": obs.method.value,
                "value": obs.value,
                "raw_span": obs.raw_span,
                "status": "normalization_failed",
            })
            continue
        by_path[obs.path].append(obs)

    merged: dict[str, MergedField] = {}

    for path, obs_list in sorted(by_path.items()):
        # Handle list-valued fields (emails, phones, skills) — aggregate.
        if path in ("emails", "phones", "skills", "links.other"):
            merged_field = _merge_list_field(path, obs_list, weights, provenance)
        else:
            merged_field = _merge_scalar_field(path, obs_list, weights, provenance)

        merged[path] = merged_field

    return merged, provenance


def _merge_scalar_field(
    path: str,
    obs_list: list[FieldObservation],
    weights: dict[str, float],
    provenance: list[dict],
) -> MergedField:
    """Merge observations for a scalar (single-value) field.

    Highest-tier observation wins. Agreement across sources boosts
    confidence. Losing values are logged in provenance.
    """
    # Score each observation by tier weight.
    scored: list[tuple[float, FieldObservation]] = []
    for obs in obs_list:
        tw = weights.get(obs.source.value, 0.5)
        mc = METHOD_CERTAINTY.get(obs.method.value, 0.5)
        score = tw * mc
        scored.append((score, obs))

    # Sort by score descending, then by source name for determinism.
    scored.sort(key=lambda x: (-x[0], x[1].source.value))

    winner_score, winner = scored[0]

    # Count agreement (how many sources agree with the winner).
    winner_norm = _normalize_for_comparison(winner.value)
    agreeing: list[str] = []
    losing: list[dict] = []

    for _score, obs in scored:
        obs_norm = _normalize_for_comparison(obs.value)
        if obs_norm == winner_norm:
            if obs.source.value not in agreeing:
                agreeing.append(obs.source.value)
        else:
            losing.append({
                "value": obs.value,
                "source": obs.source.value,
                "method": obs.method.value,
                "raw_span": obs.raw_span,
            })

    # Compute confidence.
    agreement_boost = min(1.0 + 0.1 * (len(agreeing) - 1), 1.3)
    tw = weights.get(winner.source.value, 0.5)
    mc = METHOD_CERTAINTY.get(winner.method.value, 0.5)
    confidence = round(tw * mc * agreement_boost, 4)

    # Log all observations in provenance.
    for _score, obs in scored:
        status = "winner" if _normalize_for_comparison(obs.value) == winner_norm and obs is winner else (
            "agreeing" if _normalize_for_comparison(obs.value) == winner_norm else "losing"
        )
        provenance.append({
            "field": path,
            "source": obs.source.value,
            "method": obs.method.value,
            "value": obs.value,
            "raw_span": obs.raw_span,
            "status": status,
        })

    return MergedField(
        path=path,
        value=winner.value,
        confidence=confidence,
        winning_source=winner.source.value,
        winning_method=winner.method.value,
        agreeing_sources=agreeing,
        losing_values=losing,
    )


def _merge_list_field(
    path: str,
    obs_list: list[FieldObservation],
    weights: dict[str, float],
    provenance: list[dict],
) -> MergedField:
    """Merge observations for a list-valued field (emails, phones, skills).

    All unique values are aggregated. Confidence is based on the
    highest-tier source contributing, boosted by agreement.
    """
    # Collect all unique values, preserving order.
    seen: set[str] = set()
    all_values: list[Any] = []
    sources: list[str] = []
    best_tw = 0.0
    best_mc = 0.0
    best_source = ""
    best_method = ""

    for obs in obs_list:
        tw = weights.get(obs.source.value, 0.5)
        mc = METHOD_CERTAINTY.get(obs.method.value, 0.5)
        if tw * mc > best_tw * best_mc:
            best_tw = tw
            best_mc = mc
            best_source = obs.source.value
            best_method = obs.method.value

        if obs.source.value not in sources:
            sources.append(obs.source.value)

        # Flatten list values.
        values = obs.value if isinstance(obs.value, list) else [obs.value]
        for v in values:
            v_str = str(v).strip().lower()
            if v_str not in seen:
                seen.add(v_str)
                all_values.append(v if not isinstance(v, str) else str(v).strip())

        provenance.append({
            "field": path,
            "source": obs.source.value,
            "method": obs.method.value,
            "value": obs.value,
            "raw_span": obs.raw_span,
            "status": "aggregated",
        })

    agreement_boost = min(1.0 + 0.1 * (len(sources) - 1), 1.3)
    confidence = round(best_tw * best_mc * agreement_boost, 4)

    return MergedField(
        path=path,
        value=sorted(all_values) if path != "skills" else all_values,
        confidence=confidence,
        winning_source=best_source,
        winning_method=best_method,
        agreeing_sources=sources,
        losing_values=[],
    )


def compute_overall_confidence(merged: dict[str, MergedField]) -> float:
    """Compute the overall confidence as a weighted mean of field confidences.

    Only populated (non-None) fields contribute.
    """
    confidences = [f.confidence for f in merged.values() if f.value is not None]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 4)
