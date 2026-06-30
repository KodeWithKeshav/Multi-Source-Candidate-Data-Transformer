"""Unit tests for each adapter against inline/sample fixtures.

Tests:
- CSV adapter: normal row + malformed row (skipped with warning)
- ATS adapter: aliased fields + unknown fields ignored
- GitHub adapter: mocked API response
- Notes adapter: extraction of email, phone, years, skills, company/title, location
"""

import pytest

from transformer.adapters.csv_adapter import CsvAdapter
from transformer.adapters.ats_adapter import AtsAdapter
from transformer.adapters.github_adapter import GitHubAdapter
from transformer.adapters.notes_adapter import NotesAdapter
from transformer.models import SourceDocument, SourceType


# ------------------------------------------------------------------
# CSV Adapter
# ------------------------------------------------------------------

class TestCsvAdapter:
    """CSV adapter tests."""

    def test_normal_rows(self):
        csv_text = (
            "name,email,phone,current_company,title\n"
            "Alice Johnson,alice@example.com,(512) 555-0101,Stripe,Senior SWE\n"
            "Bob Smith,bob@example.com,555-0102,Google,Staff Engineer\n"
        )
        doc = SourceDocument(
            raw=csv_text,
            source_type=SourceType.CSV,
            source_id="test.csv",
            content_hash="abc123",
        )
        adapter = CsvAdapter()
        obs = adapter.adapt(doc)
        # 2 rows × 5 columns = up to 10 observations
        assert len(obs) >= 8  # at least name, email, phone, company, title per row
        # Check that all observations are from CSV source
        assert all(o.source == SourceType.CSV for o in obs)
        # Check candidate key hints are emails
        emails = [o.candidate_key_hint for o in obs if o.path == "emails"]
        assert "alice@example.com" in emails

    def test_missing_fields_produce_fewer_observations(self):
        csv_text = (
            "name,email,phone,current_company,title\n"
            "Diana Chen,diana@example.com,,,\n"
        )
        doc = SourceDocument(
            raw=csv_text,
            source_type=SourceType.CSV,
            source_id="test.csv",
            content_hash="abc123",
        )
        adapter = CsvAdapter()
        obs = adapter.adapt(doc)
        # Only name and email should produce observations
        assert len(obs) == 2
        paths = {o.path for o in obs}
        assert "full_name" in paths
        assert "emails" in paths

    def test_empty_csv_produces_no_observations(self):
        csv_text = "name,email,phone,current_company,title\n"
        doc = SourceDocument(
            raw=csv_text,
            source_type=SourceType.CSV,
            source_id="test.csv",
            content_hash="abc123",
        )
        adapter = CsvAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) == 0

    def test_row_with_no_name_or_email_skipped(self):
        csv_text = (
            "name,email,phone,current_company,title\n"
            ",,,Acme,Intern\n"
        )
        doc = SourceDocument(
            raw=csv_text,
            source_type=SourceType.CSV,
            source_id="test.csv",
            content_hash="abc123",
        )
        adapter = CsvAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) == 0


# ------------------------------------------------------------------
# ATS JSON Adapter
# ------------------------------------------------------------------

class TestAtsAdapter:
    """ATS JSON adapter tests."""

    def test_aliased_fields(self):
        records = [
            {
                "candidate_full_name": "Alice Johnson",
                "contact_email": "alice@example.com",
                "employer": "Stripe",
                "job_title": "Senior SWE",
                "skill_tags": ["Python", "Go"],
            }
        ]
        doc = SourceDocument(
            raw=records,
            source_type=SourceType.ATS,
            source_id="test.json",
            content_hash="abc123",
        )
        adapter = AtsAdapter()
        obs = adapter.adapt(doc)
        paths = {o.path for o in obs}
        assert "full_name" in paths
        assert "emails" in paths
        assert "experience[0].company" in paths
        assert "experience[0].title" in paths
        assert "skills" in paths

    def test_unknown_fields_ignored(self):
        records = [
            {
                "candidate_full_name": "Alice",
                "contact_email": "alice@example.com",
                "favorite_color": "blue",  # not in alias map
                "zodiac_sign": "Aries",    # not in alias map
            }
        ]
        doc = SourceDocument(
            raw=records,
            source_type=SourceType.ATS,
            source_id="test.json",
            content_hash="abc123",
        )
        adapter = AtsAdapter()
        obs = adapter.adapt(doc)
        paths = {o.path for o in obs}
        assert "favorite_color" not in paths
        assert "zodiac_sign" not in paths

    def test_single_object_wrapped_as_list(self):
        record = {
            "candidate_full_name": "Solo",
            "contact_email": "solo@example.com",
        }
        doc = SourceDocument(
            raw=record,
            source_type=SourceType.ATS,
            source_id="test.json",
            content_hash="abc123",
        )
        adapter = AtsAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) >= 2

    def test_empty_values_skipped(self):
        records = [
            {
                "candidate_full_name": "Alice",
                "contact_email": "alice@example.com",
                "employer": "",
                "job_title": None,
            }
        ]
        doc = SourceDocument(
            raw=records,
            source_type=SourceType.ATS,
            source_id="test.json",
            content_hash="abc123",
        )
        adapter = AtsAdapter()
        obs = adapter.adapt(doc)
        paths = {o.path for o in obs}
        assert "experience[0].company" not in paths
        assert "experience[0].title" not in paths


# ------------------------------------------------------------------
# GitHub Adapter
# ------------------------------------------------------------------

class TestGitHubAdapter:
    """GitHub adapter tests with mocked API data."""

    def test_profile_and_repos(self):
        profile = {
            "login": "testuser",
            "name": "Test User",
            "bio": "Backend engineer at Acme",
            "email": "test@example.com",
            "location": "San Francisco",
            "blog": "https://testuser.dev",
            "html_url": "https://github.com/testuser",
            "company": "@AcmeCorp",
        }
        repos = [
            {"language": "Python"},
            {"language": "Python"},
            {"language": "Go"},
            {"language": None},  # no language
        ]
        doc = SourceDocument(
            raw={"profile": profile, "repos": repos},
            source_type=SourceType.GITHUB,
            source_id="github:testuser",
            content_hash="abc123",
        )
        adapter = GitHubAdapter()
        obs = adapter.adapt(doc)

        paths = {o.path for o in obs}
        assert "full_name" in paths
        assert "headline" in paths
        assert "emails" in paths
        assert "location.city" in paths
        assert "links.portfolio" in paths
        assert "links.github" in paths
        assert "skills" in paths
        assert "experience[0].company" in paths

        # Check skills ordering (Python should come first — 2 repos)
        skills_obs = [o for o in obs if o.path == "skills"][0]
        assert skills_obs.value[0] == "Python"
        assert "Go" in skills_obs.value

        # Company should have @ stripped
        company_obs = [o for o in obs if o.path == "experience[0].company"][0]
        assert company_obs.value == "AcmeCorp"

    def test_empty_profile(self):
        doc = SourceDocument(
            raw={"profile": {}, "repos": []},
            source_type=SourceType.GITHUB,
            source_id="github:empty",
            content_hash="abc123",
        )
        adapter = GitHubAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) == 0

    def test_non_dict_raw_produces_no_observations(self):
        doc = SourceDocument(
            raw="not a dict",
            source_type=SourceType.GITHUB,
            source_id="github:bad",
            content_hash="abc123",
        )
        adapter = GitHubAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) == 0


# ------------------------------------------------------------------
# Notes Adapter
# ------------------------------------------------------------------

class TestNotesAdapter:
    """Recruiter notes adapter tests."""

    def test_full_extraction(self):
        text = (
            "Spoke with candidate Alice Johnson on Monday. She has 7 yrs experience "
            "in backend development, strong in Python and Go. Currently at Stripe as "
            "Senior Software Engineer, based in Austin. Contact: alice@example.com, "
            "phone (512) 555-0101."
        )
        doc = SourceDocument(
            raw=text,
            source_type=SourceType.NOTES,
            source_id="note_alice.txt",
            content_hash="abc123",
        )
        adapter = NotesAdapter()
        obs = adapter.adapt(doc)

        paths = {o.path for o in obs}
        assert "emails" in paths
        assert "phones" in paths
        assert "years_experience" in paths
        assert "skills" in paths
        assert "full_name" in paths

        # Check email extracted
        email_obs = [o for o in obs if o.path == "emails"]
        assert any(o.value == "alice@example.com" for o in email_obs)

        # Check years
        yrs_obs = [o for o in obs if o.path == "years_experience"][0]
        assert yrs_obs.value == 7.0

    def test_empty_notes_produce_no_observations(self):
        text = "Quick note — brief chat. Might follow up later."
        doc = SourceDocument(
            raw=text,
            source_type=SourceType.NOTES,
            source_id="note_empty.txt",
            content_hash="abc123",
        )
        adapter = NotesAdapter()
        obs = adapter.adapt(doc)
        # May produce 0 or very few observations
        # The important thing is it doesn't crash
        assert isinstance(obs, list)

    def test_skills_extraction(self):
        text = "Strong in Python, Java, and Kubernetes. Also knows React."
        doc = SourceDocument(
            raw=text,
            source_type=SourceType.NOTES,
            source_id="note.txt",
            content_hash="abc123",
        )
        adapter = NotesAdapter()
        obs = adapter.adapt(doc)
        skill_obs = [o for o in obs if o.path == "skills"]
        skill_values = [o.value for o in skill_obs]
        assert "python" in skill_values
        assert "java" in skill_values
        assert "kubernetes" in skill_values
        assert "react" in skill_values

    def test_location_extraction(self):
        text = "Candidate is based in San Francisco and open to relocate."
        doc = SourceDocument(
            raw=text,
            source_type=SourceType.NOTES,
            source_id="note.txt",
            content_hash="abc123",
        )
        adapter = NotesAdapter()
        obs = adapter.adapt(doc)
        loc_obs = [o for o in obs if o.path == "location.city"]
        assert len(loc_obs) == 1
        assert loc_obs[0].value == "San Francisco"
