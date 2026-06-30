"""Unit tests for normalization functions.

Tests phone (E.164), date (YYYY-MM), country (ISO-3166), and skill alias
normalization — including failure cases that should yield None without crashing.
"""

import pytest

from transformer.normalize import (
    normalize_country,
    normalize_date,
    normalize_observations,
    normalize_phone,
    normalize_skill,
)
from transformer.models import ExtractionMethod, FieldObservation, SourceType


# ------------------------------------------------------------------
# Phone normalization
# ------------------------------------------------------------------

class TestNormalizePhone:
    """Phone → E.164 normalization."""

    def test_us_number_with_parens(self):
        assert normalize_phone("(512) 555-0101") == "+15125550101"

    def test_us_number_plain(self):
        assert normalize_phone("512-555-0102") == "+15125550102"

    def test_us_number_with_country_code(self):
        assert normalize_phone("+1 512-555-0103") == "+15125550103"

    def test_international_uk(self):
        assert normalize_phone("+44 20 7946 0958", "GB") == "+442079460958"

    def test_invalid_phone_returns_none(self):
        assert normalize_phone("not-a-phone") is None

    def test_empty_string_returns_none(self):
        assert normalize_phone("") is None

    def test_none_returns_none(self):
        assert normalize_phone(None) is None

    def test_too_short_returns_none(self):
        assert normalize_phone("123") is None


# ------------------------------------------------------------------
# Date normalization
# ------------------------------------------------------------------

class TestNormalizeDate:
    """Date → YYYY-MM normalization."""

    def test_yyyy_mm_passthrough(self):
        assert normalize_date("2023-06") == "2023-06"

    def test_yyyy_mm_dd(self):
        assert normalize_date("2023-06-15") == "2023-06"

    def test_mm_slash_yyyy(self):
        assert normalize_date("6/2023") == "2023-06"

    def test_month_name_yyyy(self):
        assert normalize_date("January 2022") == "2022-01"

    def test_abbr_month_yyyy(self):
        assert normalize_date("Mar 2021") == "2021-03"

    def test_year_only(self):
        assert normalize_date("2020") == "2020-01"

    def test_invalid_returns_none(self):
        assert normalize_date("not-a-date") is None

    def test_empty_returns_none(self):
        assert normalize_date("") is None


# ------------------------------------------------------------------
# Country normalization
# ------------------------------------------------------------------

class TestNormalizeCountry:
    """Country name → ISO-3166 alpha-2."""

    def test_full_name(self):
        assert normalize_country("United States") == "US"

    def test_abbreviation(self):
        assert normalize_country("USA") == "US"

    def test_already_alpha2(self):
        assert normalize_country("US") == "US"

    def test_lowercase_alpha2(self):
        assert normalize_country("gb") == "GB"

    def test_full_name_uk(self):
        assert normalize_country("United Kingdom") == "GB"

    def test_india(self):
        assert normalize_country("India") == "IN"

    def test_unknown_returns_none(self):
        assert normalize_country("Atlantis") is None

    def test_empty_returns_none(self):
        assert normalize_country("") is None


# ------------------------------------------------------------------
# Skill normalization
# ------------------------------------------------------------------

class TestNormalizeSkill:
    """Skill → canonical name via alias table."""

    def test_alias_js(self):
        assert normalize_skill("js") == "JavaScript"

    def test_alias_golang(self):
        assert normalize_skill("golang") == "Go"

    def test_alias_py(self):
        assert normalize_skill("py") == "Python"

    def test_alias_k8s(self):
        assert normalize_skill("k8s") == "Kubernetes"

    def test_alias_case_insensitive(self):
        assert normalize_skill("PYTHON") == "Python"

    def test_unknown_skill_titlecased(self):
        assert normalize_skill("fortran") == "Fortran"

    def test_unknown_multi_word(self):
        assert normalize_skill("some framework") == "Some Framework"

    def test_empty_returns_none(self):
        assert normalize_skill("") is None


# ------------------------------------------------------------------
# Batch normalize_observations
# ------------------------------------------------------------------

class TestNormalizeObservations:
    """Test the batch normalizer dispatcher."""

    def test_phone_observation_normalized(self):
        obs = [
            FieldObservation(
                path="phones",
                value="(512) 555-0101",
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT,
            )
        ]
        result = normalize_observations(obs)
        assert len(result) == 1
        assert result[0].value == "+15125550101"
        assert result[0].normalization_failed is False

    def test_phone_failure_flagged(self):
        obs = [
            FieldObservation(
                path="phones",
                value="not-a-phone",
                source=SourceType.NOTES,
                method=ExtractionMethod.REGEX,
            )
        ]
        result = normalize_observations(obs)
        assert len(result) == 1
        assert result[0].value is None
        assert result[0].normalization_failed is True

    def test_skill_list_normalized(self):
        obs = [
            FieldObservation(
                path="skills",
                value=["js", "golang", "python"],
                source=SourceType.ATS,
                method=ExtractionMethod.ALIAS_MAP,
            )
        ]
        result = normalize_observations(obs)
        assert result[0].value == ["JavaScript", "Go", "Python"]

    def test_non_phone_fields_pass_through(self):
        obs = [
            FieldObservation(
                path="full_name",
                value="Alice Johnson",
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT,
            )
        ]
        result = normalize_observations(obs)
        assert result[0].value == "Alice Johnson"
        assert result[0].normalization_failed is False
