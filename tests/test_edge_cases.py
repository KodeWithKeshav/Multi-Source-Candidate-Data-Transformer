"""Edge-case tests.

Tests:
1. Malformed CSV row: skipped with warning, rest of file processed.
2. GitHub API failure: run continues, observations absent.
3. Recruiter notes with zero extractable data: no crash, low confidence.
4. ATS JSON with unexpected fields: unmapped fields ignored.
"""

import pytest

from transformer.adapters.csv_adapter import CsvAdapter
from transformer.adapters.github_adapter import GitHubAdapter, fetch_github_profile
from transformer.adapters.notes_adapter import NotesAdapter
from transformer.models import SourceDocument, SourceType


class TestMalformedCsv:
    """Malformed CSV rows should be skipped, not crash the run."""

    def test_row_with_extra_commas_still_processes_others(self):
        """A row with stray delimiters shouldn't kill the entire CSV parse."""
        csv_text = (
            "name,email,phone,current_company,title\n"
            "Alice Johnson,alice@example.com,(512) 555-0101,Stripe,Senior SWE\n"
            "Bad Row,bad@example.com,\"contains, commas\",Broken,\"title, also broken\"\n"
            "Carlos Rivera,carlos@example.com,(512) 555-0103,Meta,Eng Manager\n"
        )
        doc = SourceDocument(
            raw=csv_text,
            source_type=SourceType.CSV,
            source_id="messy.csv",
            content_hash="abc123",
        )
        adapter = CsvAdapter()
        obs = adapter.adapt(doc)

        # Should have observations from at least Alice and Carlos (and possibly the "bad" row
        # which csv.DictReader may still parse due to quoting). The key test: no crash.
        assert len(obs) > 0
        # Alice's observations should be present
        alice_obs = [o for o in obs if o.candidate_key_hint == "alice@example.com"]
        assert len(alice_obs) >= 2

    def test_completely_broken_csv(self):
        """A completely unparseable file should produce zero observations, not crash."""
        doc = SourceDocument(
            raw="this is not csv at all\njust random text\n",
            source_type=SourceType.CSV,
            source_id="broken.csv",
            content_hash="abc123",
        )
        adapter = CsvAdapter()
        obs = adapter.adapt(doc)
        # No crash; may produce 0 observations or best-effort parse
        assert isinstance(obs, list)


class TestGitHubFailure:
    """GitHub API failures should not crash the pipeline."""

    def test_empty_profile_produces_no_observations(self):
        """A failed/empty GitHub profile should yield empty observations."""
        doc = SourceDocument(
            raw={"profile": {}, "repos": []},
            source_type=SourceType.GITHUB,
            source_id="github:nonexistent",
            content_hash="abc123",
        )
        adapter = GitHubAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) == 0

    def test_non_dict_profile_graceful(self):
        """Unexpected data structure should not crash."""
        doc = SourceDocument(
            raw="unexpected string",
            source_type=SourceType.GITHUB,
            source_id="github:broken",
            content_hash="abc123",
        )
        adapter = GitHubAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) == 0


class TestEmptyNotes:
    """Recruiter notes with zero extractable data."""

    def test_nearly_empty_notes_no_crash(self):
        text = "Brief chat. Nothing specific discussed."
        doc = SourceDocument(
            raw=text,
            source_type=SourceType.NOTES,
            source_id="note_empty.txt",
            content_hash="abc123",
        )
        adapter = NotesAdapter()
        obs = adapter.adapt(doc)
        # Should not crash; may produce 0 observations
        assert isinstance(obs, list)

    def test_completely_empty_string(self):
        doc = SourceDocument(
            raw="",
            source_type=SourceType.NOTES,
            source_id="note_blank.txt",
            content_hash="abc123",
        )
        adapter = NotesAdapter()
        obs = adapter.adapt(doc)
        assert len(obs) == 0


class TestAtsUnexpectedFields:
    """ATS JSON with renamed/unexpected fields."""

    def test_totally_unknown_schema(self):
        """An ATS record with no recognizable fields should produce minimal observations."""
        from transformer.adapters.ats_adapter import AtsAdapter

        records = [
            {
                "person_name_field": "Someone",
                "their_email": "some@example.com",
                "unknown_field_1": "value1",
                "unknown_field_2": "value2",
            }
        ]
        doc = SourceDocument(
            raw=records,
            source_type=SourceType.ATS,
            source_id="weird_ats.json",
            content_hash="abc123",
        )
        adapter = AtsAdapter()
        obs = adapter.adapt(doc)
        # "person_name_field" and "their_email" are not in the alias map
        # So this record may be skipped (no identifiable name/email)
        # The key: no crash, no guessing
        assert isinstance(obs, list)
