"""Where the DDI-CDI 1.1beta release files are: the SHACL shapes and the JSON-LD context.

Neither is vendored. They are looked up in ``validation/`` next to this repository, in
``DDI_SHACL_DIR`` and in the unpacked release (``ddi-cdi-1.1beta/build/encoding``), in
that order; a missing file skips the test that asked for it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "ddi-cdi-1.1beta" / "build" / "encoding"
SHAPES = "ddi-cdi.shacl-1-1.ttl"
CONTEXT = "ddi-cdi-1-1.jsonld"


def _dirs(release_sub: str) -> list[Path]:
    return [ROOT / "validation", Path(os.environ.get("DDI_SHACL_DIR", ROOT / "validation")), RELEASE / release_sub]


def _find(name: str, release_name: str, release_sub: str) -> Path:
    for d in _dirs(release_sub):
        for candidate in (name, release_name):
            if (d / candidate).exists():
                return d / candidate
    pytest.skip(f"{name} not found in {[str(d) for d in _dirs(release_sub)]}; set DDI_SHACL_DIR")


def find_shapes() -> Path:
    return _find(SHAPES, "ddi-cdi.shacl.ttl", "shacl")


def find_context() -> Path:
    return _find(CONTEXT, "ddi-cdi.jsonld", "json-ld")
