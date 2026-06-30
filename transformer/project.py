"""Project — apply a ProjectionConfig to produce the output JSON shape.

The canonical ``CandidateProfile`` is internal-only. This module takes
a profile and a ``ProjectionConfig`` and produces a plain dict matching
the user-requested output schema (field subset, renames, type coercion).

**Invariant:** projection never mutates the canonical record. The
ProjectionConfig logic is strictly separated from ``assemble.py``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from transformer.models import OnMissing, ProjectionConfig, ProjectionFieldConfig
from transformer.schema import CandidateProfile

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Default projection config (full schema, all fields)
# ------------------------------------------------------------------

DEFAULT_FIELDS: list[dict[str, Any]] = [
    {"path": "candidate_id", "from": "candidate_id", "type": "string", "required": True},
    {"path": "full_name", "from": "full_name", "type": "string", "required": True},
    {"path": "emails", "from": "emails", "type": "array", "required": False},
    {"path": "phones", "from": "phones", "type": "array", "required": False},
    {"path": "location", "from": "location", "type": "object", "required": False},
    {"path": "links", "from": "links", "type": "object", "required": False},
    {"path": "headline", "from": "headline", "type": "string", "required": False},
    {"path": "years_experience", "from": "years_experience", "type": "number", "required": False},
    {"path": "skills", "from": "skills", "type": "array", "required": False},
    {"path": "experience", "from": "experience", "type": "array", "required": False},
    {"path": "education", "from": "education", "type": "array", "required": False},
]


def get_default_projection_config() -> ProjectionConfig:
    """Return the default projection config (all fields, confidence + provenance on)."""
    fields = [ProjectionFieldConfig.model_validate(f) for f in DEFAULT_FIELDS]
    return ProjectionConfig(
        fields=fields,
        include_confidence=True,
        include_provenance=True,
        on_missing=OnMissing.NULL,
    )


def load_projection_config(config_path: str) -> ProjectionConfig:
    """Load a ProjectionConfig from a JSON file.

    Falls back to the default config if the file is invalid.
    """
    try:
        raw = Path(config_path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return ProjectionConfig.model_validate(data)
    except Exception as exc:
        logger.warning(
            "Failed to load projection config from %s: %s — using defaults.",
            config_path, exc,
        )
        return get_default_projection_config()


def _resolve_field(profile: CandidateProfile, from_field: str) -> Any:
    """Resolve a field value from the canonical profile.

    Supports top-level attribute names. Dotted paths and indexed paths
    are resolved by walking the model.
    """
    obj: Any = profile
    for part in from_field.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None
        if obj is None:
            return None
    return obj


def project(
    profile: CandidateProfile,
    config: ProjectionConfig,
) -> dict[str, Any]:
    """Apply a projection config to a canonical profile.

    Returns a plain dict — the output JSON shape. The canonical
    ``CandidateProfile`` is **not mutated**.
    """
    result: dict[str, Any] = {}

    for field_cfg in config.fields:
        value = _resolve_field(profile, field_cfg.from_field)

        # Determine if the value is "missing".
        is_missing = value is None or (isinstance(value, (list, dict)) and not value)

        if is_missing:
            if config.on_missing == OnMissing.NULL:
                result[field_cfg.path] = None
            elif config.on_missing == OnMissing.OMIT:
                continue  # skip this field entirely
            elif config.on_missing == OnMissing.ERROR:
                if field_cfg.required:
                    raise ValueError(
                        f"Required field '{field_cfg.path}' (from '{field_cfg.from_field}') "
                        f"is missing and on_missing='error'."
                    )
                # Non-required fields are omitted on error mode too
                continue
        else:
            result[field_cfg.path] = value

    # Optionally include confidence
    if config.include_confidence:
        result["overall_confidence"] = profile.overall_confidence
        result["field_confidences"] = profile.field_confidences

    # Optionally include provenance
    if config.include_provenance:
        result["provenance"] = profile.provenance

    return result
