"""Core data models used across the pipeline.

Defines the intermediate representations that flow between pipeline stages:
- SourceDocument: wraps raw ingested data with metadata
- FieldObservation: a single field-level observation from any adapter
- ProjectionFieldConfig / ProjectionConfig: runtime output configuration
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Source types
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    """Recognized source types for ingestion."""
    CSV = "csv"
    ATS = "ats"
    GITHUB = "github"
    NOTES = "notes"


# ---------------------------------------------------------------------------
# SourceDocument — output of the Ingest stage
# ---------------------------------------------------------------------------

class SourceDocument(BaseModel):
    """A raw ingested document wrapped with provenance metadata.

    Attributes:
        raw: The raw content (string for text sources, parsed dict/list for JSON).
        source_type: Which source category this came from.
        source_id: A human-readable identifier (filename, username, URL).
        content_hash: SHA-256 hex digest of the raw bytes, for traceability.
    """
    raw: Any
    source_type: SourceType
    source_id: str
    content_hash: str


# ---------------------------------------------------------------------------
# FieldObservation — output of the Adapt stage
# ---------------------------------------------------------------------------

class ExtractionMethod(str, Enum):
    """How a field value was obtained from the source."""
    DIRECT = "direct"
    ALIAS_MAP = "alias_map"
    API = "api"
    REGEX = "regex"
    HEURISTIC = "heuristic"


class FieldObservation(BaseModel):
    """A single field-level observation extracted by an adapter.

    Adapters never write directly to the canonical schema; they produce
    a flat list of these observations. Downstream stages (normalize,
    identity-resolution, merge) consume them.

    Attributes:
        path: Canonical field path, e.g. ``"emails"``, ``"experience[0].company"``.
        value: The extracted value (may be any JSON-serializable type).
        source: Which source produced this observation.
        method: Extraction technique used.
        raw_span: The original text fragment for audit (optional).
        candidate_key_hint: An email or name used for identity clustering.
        normalization_failed: Set to True by the normalize stage if the
            value could not be normalized; the observation is excluded
            from merge consideration but retained in the audit log.
    """
    path: str
    value: Any
    source: SourceType
    method: ExtractionMethod
    raw_span: str | None = None
    candidate_key_hint: str | None = None
    normalization_failed: bool = False


# ---------------------------------------------------------------------------
# ProjectionConfig — runtime output configuration
# ---------------------------------------------------------------------------

class OnMissing(str, Enum):
    """Behavior when a required field is absent from the canonical profile."""
    NULL = "null"
    OMIT = "omit"
    ERROR = "error"


class ProjectionFieldConfig(BaseModel):
    """Configuration for a single projected output field.

    Attributes:
        path: The output field name in the projected JSON.
        from_field: The canonical-model field to read from (``from`` in JSON,
            renamed here to avoid the Python keyword).
        type: Expected JSON type (for schema generation).
        required: Whether this field must be present in the output.
        normalize: Optional normalization hint (currently unused — all
            normalization happens before projection).
    """
    path: str
    from_field: str = Field(alias="from")
    type: str = "string"
    required: bool = False
    normalize: str | None = None

    model_config = {"populate_by_name": True}


class ProjectionConfig(BaseModel):
    """Runtime configuration that controls the output JSON shape.

    Loaded from a JSON config file (``--config``). The projection stage
    applies this **after** the canonical CandidateProfile is assembled —
    it never mutates the canonical record.

    Attributes:
        fields: List of field projection rules.
        include_confidence: Whether to include per-field and overall
            confidence scores in the output.
        include_provenance: Whether to include the provenance audit trail.
        on_missing: What to do when a required field has no value.
    """
    fields: list[ProjectionFieldConfig]
    include_confidence: bool = True
    include_provenance: bool = True
    on_missing: OnMissing = OnMissing.NULL
