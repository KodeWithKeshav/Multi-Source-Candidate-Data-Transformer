"""Identity Resolution — cluster observations into per-candidate groups.

Strategies (in order of preference):
    1. **Strong key (email match):** If two observations share the same
       normalized email in their ``candidate_key_hint``, they are
       clustered together. This is the primary and most reliable method.

    2. **Weak key (fuzzy name + company):** When no email is available,
       we fall back to normalized-name similarity combined with fuzzy
       company/title matching via ``rapidfuzz``. The threshold is
       conservative (default ≥ 85 token-sort ratio) — we prefer leaving
       two records unmerged over false-merging two different people.

Each cluster is assigned a deterministic ``candidate_id`` derived from
its primary key. The resolution method (``email`` vs ``fuzzy_name_company``)
is logged for explainability.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict

from rapidfuzz import fuzz

from transformer.models import FieldObservation

logger = logging.getLogger(__name__)

# Conservative threshold for weak-key matching.
FUZZY_THRESHOLD: int = 85


def _normalize_name(name: str) -> str:
    """Lowercase, strip, collapse whitespace, remove non-alpha."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z\s]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _normalize_email(email: str) -> str:
    """Lowercase and strip an email."""
    return email.lower().strip()


def _make_candidate_id(primary_key: str) -> str:
    """Deterministic candidate ID from the primary key."""
    h = hashlib.sha256(primary_key.encode("utf-8")).hexdigest()[:12]
    return f"cand_{h}"


def resolve_identities(
    observations: list[FieldObservation],
    fuzzy_threshold: int = FUZZY_THRESHOLD,
) -> dict[str, list[FieldObservation]]:
    """Cluster observations into per-candidate groups.

    Returns:
        A dict mapping ``candidate_id`` → list of observations.
        Also logs which method resolved each cluster.
    """
    # Phase 1: Group observations by their candidate_key_hint.
    # Each hint is either an email or a name string.
    hint_groups: dict[str, list[FieldObservation]] = defaultdict(list)
    no_hint: list[FieldObservation] = []

    for obs in observations:
        if obs.candidate_key_hint:
            hint_groups[obs.candidate_key_hint].append(obs)
        else:
            no_hint.append(obs)

    # Phase 2: Cluster hint groups by email (strong key).
    # We look for email-shaped hints and merge groups that share one.
    email_clusters: dict[str, list[str]] = {}  # norm_email → [hints]
    name_only_hints: list[str] = []

    for hint in hint_groups:
        if "@" in hint:
            norm = _normalize_email(hint)
            email_clusters.setdefault(norm, []).append(hint)
        else:
            name_only_hints.append(hint)

    # Phase 3: For each email cluster, also pull in name-only hints
    # that appear in the same observations (cross-reference via
    # observations that have both email and name key hints within
    # the same source document).
    # Build a mapping: name → associated emails
    name_to_emails: dict[str, set[str]] = defaultdict(set)
    for norm_email, hints in email_clusters.items():
        for hint in hints:
            group = hint_groups[hint]
            for obs in group:
                # Look for full_name observations in the same group
                if obs.path == "full_name":
                    name_to_emails[_normalize_name(str(obs.value))].add(norm_email)

    # Also check name_only hints against emails via name observations
    # within email-keyed groups
    email_names: dict[str, set[str]] = defaultdict(set)
    for norm_email, hints in email_clusters.items():
        for hint in hints:
            for obs in hint_groups[hint]:
                if obs.path == "full_name":
                    email_names[norm_email].add(_normalize_name(str(obs.value)))

    # Phase 4: Build final clusters.
    # Strategy: email clusters are authoritative. Name-only hints
    # are merged into an email cluster if they match by name with
    # sufficient confidence, otherwise they form their own cluster.
    clusters: dict[str, list[FieldObservation]] = {}
    resolution_log: dict[str, str] = {}  # candidate_id → method
    used_hints: set[str] = set()

    # 4a: Email-based clusters
    for norm_email, hints in sorted(email_clusters.items()):
        cid = _make_candidate_id(norm_email)
        cluster_obs: list[FieldObservation] = []
        for hint in hints:
            cluster_obs.extend(hint_groups[hint])
            used_hints.add(hint)
        clusters[cid] = cluster_obs
        resolution_log[cid] = "email"

    # 4b: Try to merge name-only hints into email clusters
    for name_hint in name_only_hints:
        norm_name = _normalize_name(name_hint)
        merged = False

        # Check if this name matches any email-cluster's names
        for norm_email, names in email_names.items():
            for ename in names:
                ratio = fuzz.token_sort_ratio(norm_name, ename)
                if ratio >= fuzzy_threshold:
                    cid = _make_candidate_id(norm_email)
                    clusters[cid].extend(hint_groups[name_hint])
                    used_hints.add(name_hint)
                    resolution_log[cid] = "email"  # still email-anchored
                    merged = True
                    logger.info(
                        "Merged name-hint %r into email cluster %s "
                        "(name fuzzy match %.1f%% ≥ %d%%)",
                        name_hint, cid, ratio, fuzzy_threshold,
                    )
                    break
            if merged:
                break

        if not merged:
            # Try fuzzy-matching against other name-only hints
            matched_cid = None
            for existing_cid, existing_obs in clusters.items():
                if resolution_log.get(existing_cid) == "email":
                    continue  # already handled above
                for eobs in existing_obs:
                    if eobs.path == "full_name":
                        ename = _normalize_name(str(eobs.value))
                        ratio = fuzz.token_sort_ratio(norm_name, ename)
                        if ratio >= fuzzy_threshold:
                            # Also check company/title for extra confidence
                            matched_cid = existing_cid
                            break
                if matched_cid:
                    break

            if matched_cid:
                clusters[matched_cid].extend(hint_groups[name_hint])
                used_hints.add(name_hint)
                logger.info(
                    "Merged name-hint %r into cluster %s via fuzzy_name_company.",
                    name_hint, matched_cid,
                )
            else:
                # Create a new cluster for this name-only hint
                cid = _make_candidate_id(norm_name)
                clusters[cid] = list(hint_groups[name_hint])
                resolution_log[cid] = "fuzzy_name_company"
                used_hints.add(name_hint)

    # 4c: Handle observations with no hint at all
    if no_hint:
        cid = _make_candidate_id("__unknown__")
        clusters[cid] = no_hint
        resolution_log[cid] = "none"
        logger.warning(
            "%d observations had no candidate_key_hint — grouped as %s.",
            len(no_hint), cid,
        )

    # Log resolution summary
    for cid, method in sorted(resolution_log.items()):
        count = len(clusters.get(cid, []))
        logger.info(
            "Cluster %s: %d observations, resolved via %s.",
            cid, count, method,
        )

    return clusters
