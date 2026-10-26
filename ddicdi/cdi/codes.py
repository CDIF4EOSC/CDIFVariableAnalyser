"""What a code is made of: its ids, its ``Category`` and its ``Notation``.

A statistic points its ``for`` at the same ``Category`` the code list enumerates, so
``jsonld`` and ``statistics`` have to build and spell these identically.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

Element = dict[str, Any]


def part(code: str) -> str:
    """A code as a fragment id part; anything but the unreserved characters is escaped."""
    return quote(code, safe="")


def code_id(variable: str, code: str) -> str:
    return f"#code-{variable}-{part(code)}"


def code_position_id(variable: str, code: str) -> str:
    return f"#codePosition-{variable}-{part(code)}"


def category_id(variable: str, code: str) -> str:
    return f"#category-{variable}-{part(code)}"


def notation_id(variable: str, code: str) -> str:
    return f"#notation-{variable}-{part(code)}"


def display_label(text: str) -> Element:
    """A ``LabelForDisplay``. The text is its ``languageSpecificString``; ``locationVariant``
    only names a locale variant ("US"), never the label itself."""
    return {
        "@type": "LabelForDisplay",
        "languageSpecificString": {"@type": "LanguageString", "content": text},
    }


def category(variable: str, code: str, label: str | None) -> Element:
    """The meaning of a code: its name is the code, its display label the value label."""
    el: Element = {
        "@id": category_id(variable, code),
        "@type": "Category",
        "name": {"@type": "ObjectName", "name": code},
    }
    if label:
        el["displayLabel"] = display_label(label)
    return el


def notation(variable: str, code: str) -> Element:
    """The sign a code is written with. Every Category needs one (SHACL minCount)."""
    return {
        "@id": notation_id(variable, code),
        "@type": "Notation",
        "content": {"@type": "TypedString", "content": code},
        "represents": category_id(variable, code),
    }
