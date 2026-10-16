"""Variable functions: what a variable *does* in the dataset, beyond its DDI-CDI role.

A variable can carry zero or more functions, for example ``Weight`` for a
sampling weight or ``UnitIdentifier`` for a case id. ``FUNCTION_NAMES`` lists
the vocabulary the n8n function-enrichment workflow (id 9OQwmjQcvhIMputR)
returns; other CamelCase names are accepted too so a newer workflow vocabulary
never gets dropped.
"""

from __future__ import annotations

import re
from typing import Iterable

FUNCTION_NAMES = (
    "UnitIdentifier",
    "GeographicDimension",
    "TemporalDimension",
    "Weight",
    "SamplingDesign",
)

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_CANONICAL = {n.lower(): n for n in FUNCTION_NAMES}


def normalize_function(value: object) -> str | None:
    """``"weight"`` / ``" Weight "`` -> ``"Weight"``; unknown but well-formed names pass
    through unchanged; anything else -> ``None``."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() in _CANONICAL:
        return _CANONICAL[text.lower()]
    return text if _NAME_RE.match(text) else None


def parse_functions(items: Iterable[str] | None) -> list[str]:
    """Validate an editor's function list: dedupe, canonicalise, reject malformed names."""
    out: list[str] = []
    for item in items or []:
        name = normalize_function(item)
        if name is None:
            raise ValueError(f"Invalid variable function {item!r}; expected a name like {FUNCTION_NAMES[3]!r}")
        if name not in out:
            out.append(name)
    return out
