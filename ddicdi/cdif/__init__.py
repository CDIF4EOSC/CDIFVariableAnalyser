"""CDIF output: the DDI-CDI document converted with the CDIF converter (vendored, Apache-2.0)."""

from __future__ import annotations

from .ddicdi_jsonld_to_cdif import convert_document
from .header import dataset_header

__all__ = ["convert_document", "dataset_header"]
