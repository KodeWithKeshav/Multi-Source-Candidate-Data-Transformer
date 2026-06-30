"""GitHub adapter — fetch profile + repos via the public REST API.

Calls:
    - ``GET https://api.github.com/users/{username}`` — profile
    - ``GET https://api.github.com/users/{username}/repos?per_page=100`` — repos

Extracts: name, bio (→ headline), public repo languages (→ skills,
weighted by repo count), blog URL (→ links.portfolio), location.

Handles 404 (nonexistent), 403 (rate-limited), timeouts, and any
other failures gracefully — they produce empty observations and a
warning, never a crash.

NOTE: LinkedIn scraping is explicitly descoped — ToS-violating and
out of scope for this project. See README for details.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from transformer.adapters.base import BaseAdapter
from transformer.models import (
    ExtractionMethod,
    FieldObservation,
    SourceDocument,
    SourceType,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT = 10  # seconds


class GitHubAdapter(BaseAdapter):
    """Adapter for GitHub public profiles."""

    def adapt(self, doc: SourceDocument) -> list[FieldObservation]:
        """Extract observations from a pre-fetched GitHub API response.

        Expects ``doc.raw`` to be a dict with keys ``profile`` and ``repos``
        (as produced by ``ingest.make_github_source_document``).
        """
        observations: list[FieldObservation] = []
        raw = doc.raw

        if not isinstance(raw, dict):
            logger.warning("GitHub source %s has unexpected structure.", doc.source_id)
            return observations

        profile: dict[str, Any] = raw.get("profile", {})
        repos: list[dict[str, Any]] = raw.get("repos", [])

        # Determine key hint
        email = profile.get("email")
        name = profile.get("name")
        login = profile.get("login", doc.source_id.removeprefix("github:"))
        key_hint = email or name or login

        # --- Name ---
        if name:
            observations.append(
                FieldObservation(
                    path="full_name",
                    value=str(name).strip(),
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(name),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Bio → headline ---
        bio = profile.get("bio")
        if bio:
            observations.append(
                FieldObservation(
                    path="headline",
                    value=str(bio).strip(),
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(bio),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Email ---
        if email:
            observations.append(
                FieldObservation(
                    path="emails",
                    value=str(email).strip(),
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(email),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Location ---
        location = profile.get("location")
        if location:
            observations.append(
                FieldObservation(
                    path="location.city",
                    value=str(location).strip(),
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(location),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Blog / portfolio link ---
        blog = profile.get("blog")
        if blog:
            observations.append(
                FieldObservation(
                    path="links.portfolio",
                    value=str(blog).strip(),
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(blog),
                    candidate_key_hint=key_hint,
                )
            )

        # --- GitHub profile link ---
        html_url = profile.get("html_url")
        if html_url:
            observations.append(
                FieldObservation(
                    path="links.github",
                    value=str(html_url).strip(),
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(html_url),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Repo languages → skills (weighted by repo count) ---
        lang_counts: dict[str, int] = {}
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            lang = repo.get("language")
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

        if lang_counts:
            # Sort by count descending for determinism
            sorted_langs = sorted(lang_counts.items(), key=lambda x: (-x[1], x[0]))
            skills_list = [lang for lang, _count in sorted_langs]
            observations.append(
                FieldObservation(
                    path="skills",
                    value=skills_list,
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(lang_counts),
                    candidate_key_hint=key_hint,
                )
            )

        # --- Company ---
        company = profile.get("company")
        if company:
            # GitHub prefixes with @ sometimes
            company_clean = str(company).strip().lstrip("@")
            observations.append(
                FieldObservation(
                    path="experience[0].company",
                    value=company_clean,
                    source=SourceType.GITHUB,
                    method=ExtractionMethod.API,
                    raw_span=str(company),
                    candidate_key_hint=key_hint,
                )
            )

        return observations


# ------------------------------------------------------------------
# Live API fetcher (called before adaptation)
# ------------------------------------------------------------------

def fetch_github_profile(username: str) -> dict[str, Any]:
    """Fetch a GitHub user's profile from the public API.

    Returns the parsed JSON dict, or an empty dict on failure.
    """
    url = f"{GITHUB_API_BASE}/users/{username}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            logger.warning("GitHub user %r not found (404).", username)
        elif resp.status_code == 403:
            logger.warning("GitHub API rate-limited (403) for user %r.", username)
        else:
            logger.warning(
                "GitHub API returned %d for user %r.", resp.status_code, username
            )
    except requests.RequestException as exc:
        logger.warning("GitHub API request failed for user %r: %s", username, exc)
    return {}


def fetch_github_repos(username: str) -> list[dict[str, Any]]:
    """Fetch a GitHub user's public repos from the public API.

    Returns a list of repo dicts, or an empty list on failure.
    """
    url = f"{GITHUB_API_BASE}/users/{username}/repos"
    try:
        resp = requests.get(
            url, params={"per_page": 100, "sort": "updated"}, timeout=REQUEST_TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.warning(
                "GitHub repos API returned %d for user %r.",
                resp.status_code, username,
            )
    except requests.RequestException as exc:
        logger.warning("GitHub repos request failed for user %r: %s", username, exc)
    return []
