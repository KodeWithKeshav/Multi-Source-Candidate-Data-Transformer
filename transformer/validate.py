"""Validate — validate projected output against a derived JSON Schema.

Before the output is written to disk, this module checks the projected
JSON against a schema derived from the ``ProjectionConfig``. It also
applies ``on_missing`` behavior for any required-but-absent fields:

    - ``null``: fills the field with ``null``
    - ``omit``: drops the key from the output
    - ``error``: raises a ``ValidationError`` naming the field
"""

from __future__ import annotations

import logging
from typing import Any

from transformer.models import OnMissing, ProjectionConfig

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when projected output fails validation."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"Validation error for field '{field}': {message}")


# ------------------------------------------------------------------
# Type-check helpers
# ------------------------------------------------------------------

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _check_type(value: Any, expected_type: str) -> bool:
    """Check if *value* matches the expected JSON type string."""
    if value is None:
        return True  # null is always acceptable
    check = _TYPE_CHECKS.get(expected_type)
    if check is None:
        return True  # unknown type — pass
    return isinstance(value, check)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def validate_output(
    projected: dict[str, Any],
    config: ProjectionConfig,
) -> dict[str, Any]:
    """Validate and finalize the projected output.

    Applies ``on_missing`` behavior for required-but-absent fields and
    type-checks all present fields. Returns the (possibly modified)
    projected dict.

    Raises:
        ValidationError: if ``on_missing == "error"`` and a required
            field is missing.
    """
    result = dict(projected)  # shallow copy

    for field_cfg in config.fields:
        path = field_cfg.path
        value = result.get(path)

        is_missing = (
            path not in result
            or value is None
            or (isinstance(value, (list, dict)) and not value)
        )

        if is_missing and field_cfg.required:
            if config.on_missing == OnMissing.ERROR:
                raise ValidationError(
                    path,
                    f"Required field is missing (from='{field_cfg.from_field}').",
                )
            elif config.on_missing == OnMissing.OMIT:
                result.pop(path, None)
            elif config.on_missing == OnMissing.NULL:
                result[path] = None

        elif not is_missing:
            # Type check
            if not _check_type(value, field_cfg.type):
                logger.warning(
                    "Field '%s' has type %s, expected %s — keeping value.",
                    path, type(value).__name__, field_cfg.type,
                )

    return result
