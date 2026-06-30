"""Normalize — pure functions applied per-observation before merge.

Each normalizer converts a raw value into its canonical form. On failure
the value is set to ``None`` and ``normalization_failed`` is flagged on
the observation — it is excluded from merge consideration but **retained
in the audit log**. Nothing is silently dropped; nothing is invented.

Normalizers:
    - phone  → E.164 via the ``phonenumbers`` library
    - date   → ``YYYY-MM``
    - country → ISO-3166 alpha-2
    - skill  → canonical name via a curated alias dictionary
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from datetime import datetime

import phonenumbers

from transformer.models import FieldObservation

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Curated lookup tables
# ------------------------------------------------------------------

# Skill alias map: lowercased alias → canonical name.
# Expand as needed; this is intentionally conservative.
SKILL_ALIASES: dict[str, str] = {
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "py": "Python",
    "python": "Python",
    "golang": "Go",
    "go": "Go",
    "rb": "Ruby",
    "ruby": "Ruby",
    "java": "Java",
    "c#": "C#",
    "csharp": "C#",
    "c++": "C++",
    "cpp": "C++",
    "rust": "Rust",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "scala": "Scala",
    "r": "R",
    "php": "PHP",
    "sql": "SQL",
    "html": "HTML",
    "css": "CSS",
    "shell": "Shell",
    "bash": "Shell",
    "powershell": "PowerShell",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "angular": "Angular",
    "angularjs": "Angular",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "spring": "Spring",
    "rails": "Ruby on Rails",
    "ruby on rails": "Ruby on Rails",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "terraform": "Terraform",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "graphql": "GraphQL",
    "rest": "REST",
    "grpc": "gRPC",
    "kafka": "Kafka",
    "spark": "Apache Spark",
    "hadoop": "Hadoop",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "ai": "AI",
    "nlp": "NLP",
    "cv": "Computer Vision",
    "computer vision": "Computer Vision",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "tf": "TensorFlow",
    "objective-c": "Objective-C",
    "objc": "Objective-C",
    "elixir": "Elixir",
    "erlang": "Erlang",
    "haskell": "Haskell",
    "lua": "Lua",
    "perl": "Perl",
    "dart": "Dart",
    "flutter": "Flutter",
    "svelte": "Svelte",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "nuxt": "Nuxt.js",
    "nuxt.js": "Nuxt.js",
    "express": "Express.js",
    "expressjs": "Express.js",
    "express.js": "Express.js",
    "jupyter notebook": "Jupyter Notebook",
    "jupyter": "Jupyter Notebook",
    "c": "C",
    "makefile": "Makefile",
    "cmake": "CMake",
}

# Country name → ISO-3166 alpha-2.  Intentionally small; extend as needed.
COUNTRY_MAP: dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "us": "US",
    "united states of america": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "india": "IN",
    "japan": "JP",
    "china": "CN",
    "brazil": "BR",
    "mexico": "MX",
    "spain": "ES",
    "italy": "IT",
    "netherlands": "NL",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "ireland": "IE",
    "new zealand": "NZ",
    "singapore": "SG",
    "south korea": "KR",
    "israel": "IL",
    "portugal": "PT",
    "poland": "PL",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
}


# ------------------------------------------------------------------
# Individual normalizers
# ------------------------------------------------------------------

def normalize_phone(value: str, default_region: str | None = None) -> str | None:
    """Normalize a phone number to E.164 format.

    Uses the ``phonenumbers`` library. Falls back to *default_region*
    when the number has no country code. Returns ``None`` on failure.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = phonenumbers.parse(value, default_region or "US")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
    except phonenumbers.NumberParseException:
        pass
    logger.debug("Phone normalization failed for %r", value)
    return None


def normalize_date(value: str) -> str | None:
    """Normalize a date string to ``YYYY-MM`` format.

    Handles common formats: ``YYYY-MM-DD``, ``MM/YYYY``, ``Month YYYY``,
    ``YYYY-MM``, etc. Returns ``None`` on failure.
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()

    # Already YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", value):
        return value

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/]\d{1,2}$", value)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"

    # MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{4})$", value)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"

    # "Month YYYY" or "Mon YYYY"
    for fmt in ("%B %Y", "%b %Y"):
        try:
            dt = datetime.strptime(value, fmt)
            return f"{dt.year}-{dt.month:02d}"
        except ValueError:
            continue

    # Just a year
    m = re.match(r"^(\d{4})$", value)
    if m:
        return f"{m.group(1)}-01"

    logger.debug("Date normalization failed for %r", value)
    return None


def normalize_country(value: str) -> str | None:
    """Normalize a country name to ISO-3166 alpha-2 code.

    Uses a curated lookup table. Returns ``None`` if unrecognized.
    Already-valid two-letter codes are passed through.
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()

    # Already an alpha-2 code?
    if len(value) == 2 and value.isalpha():
        return value.upper()

    canonical = COUNTRY_MAP.get(value.lower())
    if canonical:
        return canonical

    logger.debug("Country normalization failed for %r", value)
    return None


def normalize_skill(value: str) -> str | None:
    """Map a skill name to its canonical form via the alias table.

    Returns ``None`` only if the value is empty. Unrecognized skills
    are **kept as-is** (title-cased) — they are not dropped.
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    canonical = SKILL_ALIASES.get(value.lower())
    if canonical:
        return canonical
    # Not in the alias table — keep the original, title-cased.
    return value.title() if value else None


# ------------------------------------------------------------------
# Batch normalizer — dispatches per observation path
# ------------------------------------------------------------------

def normalize_observations(
    observations: list[FieldObservation],
) -> list[FieldObservation]:
    """Apply the appropriate normalizer to each observation based on its path.

    Returns a new list — the originals are not mutated.  Observations
    whose normalization fails have ``normalization_failed=True`` and
    ``value=None`` but are **kept** in the list for audit purposes.
    """
    result: list[FieldObservation] = []
    for obs in observations:
        obs = deepcopy(obs)

        if obs.path == "phones" and obs.value is not None:
            normalized = normalize_phone(str(obs.value))
            if normalized is None:
                obs.normalization_failed = True
                logger.warning(
                    "Phone normalization failed for %r from source=%s",
                    obs.value, obs.source,
                )
            obs.value = normalized

        elif obs.path == "location.country" and obs.value is not None:
            normalized = normalize_country(str(obs.value))
            if normalized is None:
                obs.normalization_failed = True
                logger.warning(
                    "Country normalization failed for %r from source=%s",
                    obs.value, obs.source,
                )
            obs.value = normalized

        elif obs.path == "skills" and obs.value is not None:
            if isinstance(obs.value, list):
                obs.value = [normalize_skill(s) for s in obs.value]
                obs.value = [s for s in obs.value if s is not None]
            else:
                normalized = normalize_skill(str(obs.value))
                if normalized is None:
                    obs.normalization_failed = True
                obs.value = normalized

        elif (
            obs.path.endswith(".start")
            or obs.path.endswith(".end")
            or obs.path.endswith(".end_year")
        ) and obs.value is not None:
            normalized = normalize_date(str(obs.value))
            if normalized is None:
                obs.normalization_failed = True
                logger.warning(
                    "Date normalization failed for %r from source=%s",
                    obs.value, obs.source,
                )
            obs.value = normalized

        result.append(obs)
    return result
