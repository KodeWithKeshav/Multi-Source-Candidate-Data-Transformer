"""Merge & confidence scoring tests.

Tests:
1. Same-tier disagreement resolved correctly; losing value logged in provenance.
2. Agreement boost when multiple sources agree on the same value.
3. Overall confidence computation.
"""

import pytest

from transformer.merge import (
    MergedField,
    compute_overall_confidence,
    merge_observations,
)
from transformer.models import ExtractionMethod, FieldObservation, SourceType


class TestScalarMerge:
    """Test scalar field merge logic."""

    def test_higher_tier_wins(self):
        """ATS (tier 0.9) should beat CSV (tier 0.7) for the same field."""
        obs = [
            FieldObservation(
                path="full_name",
                value="Robert Smith",
                source=SourceType.ATS,
                method=ExtractionMethod.ALIAS_MAP,
                candidate_key_hint="bob@example.com",
            ),
            FieldObservation(
                path="full_name",
                value="Bob Smith",
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT,
                candidate_key_hint="bob@example.com",
            ),
        ]
        merged, provenance = merge_observations(obs)

        assert "full_name" in merged
        # ATS has tier 0.9 × method 0.95 = 0.855
        # CSV has tier 0.7 × method 1.0  = 0.7
        # ATS wins
        assert merged["full_name"].value == "Robert Smith"
        assert merged["full_name"].winning_source == "ats"

        # Losing value should be in provenance
        losing_entries = [
            p for p in provenance
            if p["field"] == "full_name" and p["status"] == "losing"
        ]
        assert len(losing_entries) == 1
        assert losing_entries[0]["value"] == "Bob Smith"
        assert losing_entries[0]["source"] == "csv"

    def test_agreement_boosts_confidence(self):
        """When CSV and ATS agree on the same value, confidence should be boosted."""
        obs = [
            FieldObservation(
                path="full_name",
                value="Alice Johnson",
                source=SourceType.ATS,
                method=ExtractionMethod.ALIAS_MAP,
                candidate_key_hint="alice@example.com",
            ),
            FieldObservation(
                path="full_name",
                value="Alice Johnson",
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT,
                candidate_key_hint="alice@example.com",
            ),
        ]
        merged, _ = merge_observations(obs)

        field = merged["full_name"]
        # ATS: 0.9 × 0.95 × agreement_boost(2 sources) = 0.855 × 1.1 = 0.9405
        assert field.confidence > 0.9  # boosted above base
        assert len(field.agreeing_sources) == 2

    def test_notes_lower_than_csv(self):
        """Notes (tier 0.4) should lose to CSV (tier 0.7)."""
        obs = [
            FieldObservation(
                path="experience[0].company",
                value="Stripe Inc",
                source=SourceType.NOTES,
                method=ExtractionMethod.HEURISTIC,
            ),
            FieldObservation(
                path="experience[0].company",
                value="Stripe",
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT,
            ),
        ]
        merged, provenance = merge_observations(obs)
        assert merged["experience[0].company"].winning_source == "csv"


class TestListMerge:
    """Test list field merge logic."""

    def test_skills_aggregated_from_multiple_sources(self):
        """Skills from multiple sources should be aggregated (union)."""
        obs = [
            FieldObservation(
                path="skills",
                value=["Python", "Go"],
                source=SourceType.ATS,
                method=ExtractionMethod.ALIAS_MAP,
            ),
            FieldObservation(
                path="skills",
                value="Kubernetes",
                source=SourceType.NOTES,
                method=ExtractionMethod.HEURISTIC,
            ),
        ]
        merged, _ = merge_observations(obs)
        skills = merged["skills"]
        assert "Python" in skills.value
        assert "Go" in skills.value
        assert "Kubernetes" in skills.value

    def test_emails_deduplicated(self):
        """Duplicate emails from different sources should be deduplicated."""
        obs = [
            FieldObservation(
                path="emails",
                value="alice@example.com",
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT,
            ),
            FieldObservation(
                path="emails",
                value="alice@example.com",
                source=SourceType.ATS,
                method=ExtractionMethod.ALIAS_MAP,
            ),
        ]
        merged, _ = merge_observations(obs)
        assert len(merged["emails"].value) == 1


class TestOverallConfidence:
    """Test overall confidence computation."""

    def test_weighted_mean(self):
        merged = {
            "a": MergedField("a", "val", 0.8, "ats", "direct", [], []),
            "b": MergedField("b", "val", 0.6, "csv", "direct", [], []),
        }
        overall = compute_overall_confidence(merged)
        assert overall == pytest.approx(0.7, abs=0.01)

    def test_none_values_excluded(self):
        merged = {
            "a": MergedField("a", "val", 0.8, "ats", "direct", [], []),
            "b": MergedField("b", None, 0.0, "", "", [], []),
        }
        overall = compute_overall_confidence(merged)
        assert overall == pytest.approx(0.8, abs=0.01)

    def test_empty_merged_returns_zero(self):
        assert compute_overall_confidence({}) == 0.0


class TestConfidenceCap:
    """Confidence scores must never exceed 1.0."""

    def test_three_agreeing_high_tier_sources_capped_at_one(self):
        """Three ATS sources agreeing would produce 0.9 × 0.95 × 1.2 = 1.026
        without a cap. With the cap, the confidence must be exactly 1.0."""
        obs = [
            FieldObservation(
                path="full_name",
                value="Alice Johnson",
                source=SourceType.ATS,
                method=ExtractionMethod.ALIAS_MAP,
                candidate_key_hint="alice@example.com",
            ),
            FieldObservation(
                path="full_name",
                value="Alice Johnson",
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT,
                candidate_key_hint="alice@example.com",
            ),
            FieldObservation(
                path="full_name",
                value="Alice Johnson",
                source=SourceType.NOTES,
                method=ExtractionMethod.REGEX,
                candidate_key_hint="alice@example.com",
            ),
        ]
        merged, _ = merge_observations(obs)
        conf = merged["full_name"].confidence
        assert conf <= 1.0, f"Confidence {conf} exceeds 1.0"
        assert conf == 1.0, f"Expected exactly 1.0 for capped high-agreement, got {conf}"
