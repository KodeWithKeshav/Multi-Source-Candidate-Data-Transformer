"""Base adapter interface.

All source adapters inherit from ``BaseAdapter`` and implement
the ``adapt`` method, which converts a ``SourceDocument`` into
a list of ``FieldObservation`` objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from transformer.models import FieldObservation, SourceDocument


class BaseAdapter(ABC):
    """Abstract base class for source adapters.

    An adapter is responsible for extracting field-level observations
    from a single source document. It must **never** write directly
    to the canonical schema — only produce ``FieldObservation`` objects.

    A malformed/missing source must produce zero or partial observations
    and a logged warning — never an exception that kills the run.
    """

    @abstractmethod
    def adapt(self, doc: SourceDocument) -> list[FieldObservation]:
        """Extract observations from *doc*.

        Returns a (possibly empty) list of ``FieldObservation`` objects.
        """
        ...
