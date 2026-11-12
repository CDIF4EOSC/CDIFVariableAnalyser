"""Variable role assignment (measure / identifier / attribute)."""

from __future__ import annotations

from .models import DatasetMeta, Roles

ROLE_NAMES = ("measure", "identifier", "attribute")
# "measure,identifier,attribute" is 29 characters; anything far longer is not a role list.
MAX_ROLE_TEXT = 100


def default_roles(meta: DatasetMeta) -> dict[str, str]:
    """Every variable of a wide (SPSS/Stata/CSV) dataset defaults to ``measure``."""
    return {name: "measure" for name in meta.column_names}


def parse_roles(meta: DatasetMeta, assignments: dict[str, str] | None) -> Roles:
    """Turn ``{"idno": "identifier", "cntry": "measure,attribute"}`` into role lists.

    Unassigned variables fall back to ``measure``. Unknown variables or role
    names raise ``ValueError``.
    """
    roles = Roles()
    assignments = assignments or {}
    unknown = set(assignments) - set(meta.column_names)
    if unknown:
        raise ValueError(f"Unknown variables in role assignment: {sorted(unknown)}")

    for name in meta.column_names:
        for part in split_roles(assignments.get(name, "measure"), name):
            getattr(roles, part).append(name)
    return roles


def split_roles(raw: str | None, name: str) -> list[str]:
    """``"measure, attribute"`` -> ``["measure", "attribute"]``: each role once, in order.

    An empty value means ``measure``. A value longer than :data:`MAX_ROLE_TEXT` or with
    an unknown role raises ``ValueError``; repeated roles are kept once, so a variable is
    never listed twice under the same role.
    """
    raw = raw or "measure"
    if len(raw) > MAX_ROLE_TEXT:
        raise ValueError(f"Role for variable {name!r} is longer than {MAX_ROLE_TEXT} characters")
    parts = list(dict.fromkeys(p.strip().lower() for p in raw.split(",") if p.strip())) or ["measure"]
    for part in parts:
        if part not in ROLE_NAMES:
            raise ValueError(f"Unknown role {part!r} for variable {name!r}; valid: {ROLE_NAMES}")
    return parts


def roles_to_assignments(roles: Roles) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for role in ROLE_NAMES:
        for name in getattr(roles, role):
            out.setdefault(name, []).append(role)
    return {k: ",".join(v) for k, v in out.items()}
