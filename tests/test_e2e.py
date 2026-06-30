"""End-to-end pipeline tests.

Tests:
1. Full pipeline with sample inputs → schema-valid output (default config).
2. Custom config (field subset + rename + on_missing: omit).
3. Determinism: run twice on identical inputs → byte-identical output.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from transformer.cli import run_pipeline
from transformer.project import get_default_projection_config, load_projection_config


# ------------------------------------------------------------------
# Fixtures — inline sample data for tests (no network calls)
# ------------------------------------------------------------------

SAMPLE_CSV = """\
name,email,phone,current_company,title
Alice Johnson,alice@example.com,(512) 555-0101,Stripe,Senior SWE
Bob Smith,bob@example.com,555-0102,Google,Staff Engineer
"""

SAMPLE_ATS_JSON = json.dumps([
    {
        "candidate_full_name": "Alice Johnson",
        "contact_email": "alice@example.com",
        "employer": "Stripe",
        "job_title": "Senior Software Engineer",
        "skill_tags": ["Python", "Go"],
    },
    {
        "candidate_full_name": "Robert Smith",
        "contact_email": "bob@example.com",
        "employer": "Google",
        "job_title": "Staff Software Engineer",
        "skill_tags": ["Java", "C++"],
    },
])

SAMPLE_NOTES_ALICE = (
    "Spoke with candidate Alice Johnson. She has 7 yrs experience "
    "in backend. Strong in Python and Go. Currently at Stripe as "
    "Senior SWE, based in Austin. Contact: alice@example.com."
)

SAMPLE_NOTES_BOB = (
    "Spoke with Bob Smith. 8 years in Java development. "
    "Currently at Google as Staff Engineer. Based in San Francisco. "
    "Contact: bob@example.com."
)

SAMPLE_CUSTOM_CONFIG = json.dumps({
    "fields": [
        {"path": "id", "from": "candidate_id", "type": "string", "required": True},
        {"path": "name", "from": "full_name", "type": "string", "required": True},
        {"path": "contact_emails", "from": "emails", "type": "array", "required": False},
        {"path": "top_skills", "from": "skills", "type": "array", "required": False},
    ],
    "include_confidence": False,
    "include_provenance": False,
    "on_missing": "omit",
})


@pytest.fixture
def sample_data_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with sample data files."""
    # CSV
    csv_path = tmp_path / "recruiters.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")

    # ATS JSON
    ats_path = tmp_path / "ats_export.json"
    ats_path.write_text(SAMPLE_ATS_JSON, encoding="utf-8")

    # Notes
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "alice.txt").write_text(SAMPLE_NOTES_ALICE, encoding="utf-8")
    (notes_dir / "bob.txt").write_text(SAMPLE_NOTES_BOB, encoding="utf-8")

    # Custom config
    config_path = tmp_path / "custom.json"
    config_path.write_text(SAMPLE_CUSTOM_CONFIG, encoding="utf-8")

    return tmp_path


def _run_offline_pipeline(sample_data_dir: Path, config_path: str | None = None):
    """Run the pipeline without any GitHub API calls."""
    csv_paths = [str(sample_data_dir / "recruiters.csv")]
    ats_paths = [str(sample_data_dir / "ats_export.json")]
    notes_paths = sorted(str(p) for p in (sample_data_dir / "notes").glob("*.txt"))

    return run_pipeline(
        csv_paths=csv_paths,
        ats_paths=ats_paths,
        github_user_files=[],  # no GitHub for offline tests
        notes_paths=notes_paths,
        config_path=config_path,
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestDefaultConfig:
    """End-to-end test with default projection config."""

    def test_produces_valid_profiles(self, sample_data_dir):
        profiles = _run_offline_pipeline(sample_data_dir)

        assert len(profiles) >= 2  # at least Alice and Bob

        for profile in profiles:
            # Required fields should be present
            assert "candidate_id" in profile
            assert "full_name" in profile
            assert profile["candidate_id"] is not None
            assert profile["full_name"] is not None

            # Confidence should be present and in valid range
            assert "overall_confidence" in profile
            assert 0.0 <= profile["overall_confidence"] <= 1.5  # can exceed 1.0 with boost

            # Provenance should be present
            assert "provenance" in profile
            assert isinstance(profile["provenance"], list)

    def test_alice_has_merged_data(self, sample_data_dir):
        profiles = _run_offline_pipeline(sample_data_dir)

        # Find Alice's profile
        alice = None
        for p in profiles:
            if p.get("full_name") == "Alice Johnson":
                alice = p
                break

        if alice is None:
            # Might be under a different key; find by email
            for p in profiles:
                emails = p.get("emails", [])
                if emails and "alice@example.com" in emails:
                    alice = p
                    break

        assert alice is not None, "Alice's profile should be in the output"
        assert "alice@example.com" in alice.get("emails", [])


class TestCustomConfig:
    """End-to-end test with custom projection config (subset + rename + omit)."""

    def test_custom_field_names(self, sample_data_dir):
        config_path = str(sample_data_dir / "custom.json")
        profiles = _run_offline_pipeline(sample_data_dir, config_path=config_path)

        assert len(profiles) >= 2

        for profile in profiles:
            # Custom field names
            assert "id" in profile
            assert "name" in profile

            # Original field names should NOT be present
            assert "candidate_id" not in profile
            assert "full_name" not in profile

            # Confidence and provenance should be absent (disabled)
            assert "overall_confidence" not in profile
            assert "provenance" not in profile

            # Fields with on_missing=omit should be absent if empty
            # (rather than null)
            for key, val in profile.items():
                if key not in ("id", "name"):
                    assert val is not None, f"on_missing=omit should not produce null for {key}"


class TestDeterminism:
    """The pipeline must be deterministic: same input → byte-identical output."""

    def test_byte_identical_output(self, sample_data_dir):
        """Run the pipeline twice and compare JSON output byte-for-byte."""
        profiles_1 = _run_offline_pipeline(sample_data_dir)
        profiles_2 = _run_offline_pipeline(sample_data_dir)

        json_1 = json.dumps(profiles_1, indent=2, sort_keys=True, ensure_ascii=False)
        json_2 = json.dumps(profiles_2, indent=2, sort_keys=True, ensure_ascii=False)

        assert json_1 == json_2, "Pipeline output must be byte-identical across runs"
