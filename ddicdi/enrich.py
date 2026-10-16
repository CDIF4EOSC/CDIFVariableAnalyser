"""AI suggestions for variable metadata via the n8n enrichment webhooks.

Five webhooks (shared with the SoGreen provenance editor) take
``{"variables": [VariableInput, ...]}`` (built by ``variable_input``) and return
``{"results": [...]}``:

* units: one batched call, ``results[].unit_of_measure`` is an EU Publications
  Office measurement-unit URI (or ``""``);
* ELSST concepts: **one call per variable** (the n8n loop intermittently returns
  an empty body for multi-item input), ``results[].elsst_concepts`` is a list of
  ``{uri, pref_label}``;
* variable roles: batched calls (``BATCH_SIZE`` variables each); the body is
  ``[{"results": [...], "ok", "failed", "total"}]`` (a one-element array) with
  ``results[].component_role`` = ``IdentifierComponent`` / ``MeasureComponent`` /
  ``AttributeComponent`` and ``results[].status`` = ``"ok"``. Other spellings
  (``role``, a list, comma-separated) are accepted too;
* variable functions: same batched shape as roles, ``results[].variable_function``
  is a list of ``UnitIdentifier`` / ``GeographicDimension`` / ``TemporalDimension`` /
  ``Weight`` / ``SamplingDesign`` (empty for most substantive variables);
* level of measurement: same batched shape, ``results[].measure`` is ``Scale`` /
  ``Ordinal`` / ``Nominal`` (lower-cased here to match ``Variable.measure``). That
  workflow drops ``variable_measure`` from its input so the model is not nudged into
  echoing the file's current level.

Only suggestions are produced here; persisting them is the caller's decision.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

from .config import settings
from .functions import normalize_function
from .models import Variable
from .roles import ROLE_NAMES

BASE_UNIT_URI = "http://publications.europa.eu/resource/authority/measurement-unit/"
MAX_VALUE_LABELS = 15  # the workflows' cap too
ATTEMPTS = 3
KINDS = ("unit", "concept", "role", "function", "measure")
FIELD_BY_KIND = {
    "unit": "unit_of_measure",
    "concept": "concepts",
    "role": "role",
    "function": "functions",
    "measure": "measure",
}
MEASURE_KEYS = ("measure", "measurement_level", "level_of_measurement", "measure_level", "spss_measure")
MEASURE_ALIASES = {
    "nominal": "nominal",
    "ordinal": "ordinal",
    "scale": "scale",
    "interval": "scale",
    "ratio": "scale",
    "continuous": "scale",
    "numeric": "scale",
    "categorical": "nominal",
}
FUNCTION_KEYS = ("variable_function", "variable_functions", "functions", "function", "variableFunction")
ROLE_KEYS = ("component_role", "role", "variable_role", "roles", "ddi_role", "suggested_role")
ROLE_ALIASES = {
    "measure": "measure",
    "measures": "measure",
    "identifier": "identifier",
    "identifiers": "identifier",
    "identifiercomponent": "identifier",
    "measurecomponent": "measure",
    "attributecomponent": "attribute",
    "id": "identifier",
    "key": "identifier",
    "dimension": "identifier",
    "attribute": "attribute",
    "attributes": "attribute",
}
BATCH_SIZE = 20  # variables per batched webhook call (units, roles, functions)
BACKOFF = 1.0  # seconds; multiplied by the attempt number (tests set it to 0)


class NotConfigured(RuntimeError):
    """No bearer key: the feature is switched off."""


class EnrichError(RuntimeError):
    """A webhook call failed after all attempts."""


@dataclass
class EnrichResult:
    suggestions: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> {unit_of_measure?, concepts?, role?, functions?}
    errors: list[dict[str, Any]] = field(default_factory=list)  # {name, kind, message}


# -- payload ----------------------------------------------------------------------------


def _missing_values(var: Variable) -> list[str]:
    out = []
    for r in var.missing_ranges:
        d = r.to_dict()
        out.append(d["lo"] if d["lo"] == d["hi"] else f"{d['lo']}-{d['hi']}")
    return out


def variable_input(var: Variable) -> dict[str, Any]:
    """The shared ``VariableInput`` every enrichment workflow accepts (see
    metadata-enrichment-pipelines ``schemas/variable_input.py``).

    Every kind gets the same item, and each workflow passes all of it to its LLM -- except
    the measure workflow, which drops ``variable_measure`` so it is not echoed back.
    Value labels are the substantive ones, capped at ``MAX_VALUE_LABELS``; missing codes
    go in ``variable_missing_values``. Empty fields are left out."""
    labels = [{"value": c, "label": var.value_labels[c]} for c in var.substantive_codes()]
    item: dict[str, Any] = {
        "variable_name": var.name,
        "variable_label": var.label,
        "variable_datatype": var.storage_type,
        "variable_format": var.format,
        "variable_measure": var.measure if var.measure != "unknown" else None,
        "variable_value_labels": labels[:MAX_VALUE_LABELS],
        "variable_value_labels_total": len(labels) if labels else None,
        "variable_missing_values": _missing_values(var),
    }
    return {k: v for k, v in item.items() if v not in (None, "", [])}


# -- normalisation ----------------------------------------------------------------------


def normalize_unit(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        return text
    if text.isalnum() and 2 <= len(text) <= 3:
        return BASE_UNIT_URI + text.upper()
    return None


def normalize_concepts(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for c in items or []:
        if not isinstance(c, dict):
            continue
        uri = str(c.get("uri", "") or "").strip()
        if not uri.startswith(("http://", "https://")) or uri in seen:
            continue
        seen.add(uri)
        out.append({"uri": uri, "pref_label": str(c.get("pref_label", "") or "").strip()})
    return out


def normalize_role(value: Any) -> str | None:
    """Turn ``"identifier"``, ``"Measure, Attribute"`` or ``["measure", "attribute"]`` into
    a canonical comma-joined role string in ``ROLE_NAMES`` order; ``None`` if nothing valid."""
    if isinstance(value, dict):
        value = next((value[k] for k in ROLE_KEYS if k in value), None)
    if isinstance(value, str):
        parts = re.split(r"[,;/|+&\s]+", value)
    elif isinstance(value, (list, tuple)):
        parts = [str(p) for p in value]
    else:
        return None
    found = {ROLE_ALIASES[p.strip().lower()] for p in parts if p.strip().lower() in ROLE_ALIASES}
    if not found:
        return None
    return ",".join(r for r in ROLE_NAMES if r in found)


def role_from_result(row: dict) -> str | None:
    for key in ROLE_KEYS:
        if key in row:
            return normalize_role(row[key])
    return None


def normalize_functions(value: Any) -> list[str]:
    """Turn ``["Weight"]``, ``"Weight, SamplingDesign"`` or ``"weight"`` into a deduplicated
    list of canonical function names; unknown or empty input gives ``[]``."""
    if isinstance(value, dict):
        value = next((value[k] for k in FUNCTION_KEYS if k in value), None)
    if isinstance(value, str):
        parts: list[Any] = re.split(r"[,;/|+&]+", value)
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return []
    out: list[str] = []
    for p in parts:
        name = normalize_function(p)
        if name is not None and name not in out:
            out.append(name)
    return out


def functions_from_result(row: dict) -> list[str] | None:
    for key in FUNCTION_KEYS:
        if key in row:
            return normalize_functions(row[key])
    return None


def normalize_measure(value: Any) -> str | None:
    """``"Scale"`` / ``"ordinal"`` / ``"Nominal"`` (plus interval/ratio -> scale) to the
    lower-case ``Variable.measure`` value; ``None`` for anything else."""
    if isinstance(value, dict):
        value = next((value[k] for k in MEASURE_KEYS if k in value), None)
    if not isinstance(value, str):
        return None
    return MEASURE_ALIASES.get(value.strip().lower())


def measure_from_result(row: dict) -> str | None:
    for key in MEASURE_KEYS:
        if key in row:
            return normalize_measure(row[key])
    return None


# -- HTTP ---------------------------------------------------------------------------------


async def _post(client: httpx.AsyncClient, url: str, payload: dict, headers: dict[str, str]) -> dict:
    last = "no attempts"
    for attempt in range(ATTEMPTS):
        try:
            r = await client.post(url, json=payload, headers=headers)
            if 400 <= r.status_code < 500:
                raise EnrichError(f"n8n returned {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
                data = data[0]  # some workflows respond with a one-element array
            if not isinstance(data, dict):
                raise ValueError("response is not a JSON object")
            return data
        except EnrichError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < ATTEMPTS - 1:
            await asyncio.sleep(2 * BACKOFF * (attempt + 1))
    raise EnrichError(f"n8n call failed after {ATTEMPTS} attempts ({last})")


def _batches(variables: list[Variable]) -> list[list[Variable]]:
    return [variables[i : i + BATCH_SIZE] for i in range(0, len(variables), BATCH_SIZE)]


async def _batched(
    client: httpx.AsyncClient,
    variables: list[Variable],
    headers: dict[str, str],
    url: str,
    kind: str,
) -> tuple[dict[str, dict], list[dict[str, Any]]]:
    """POST the variables in batches; return ``results`` rows by name plus per-batch errors."""
    by_name: dict[str, dict] = {}
    errors: list[dict[str, Any]] = []

    async def one(batch: list[Variable]) -> None:
        try:
            data = await _post(client, url, {"variables": [variable_input(v) for v in batch]}, headers)
        except EnrichError as exc:
            errors.append({"name": None, "kind": kind, "message": str(exc)})
            return
        for r in data.get("results", []):
            if isinstance(r, dict):
                by_name[str(r.get("variable_name"))] = r

    await asyncio.gather(*(one(b) for b in _batches(variables)))
    return by_name, errors


async def suggest_units(
    client: httpx.AsyncClient, variables: list[Variable], headers: dict[str, str], url: str
) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    if not variables:
        return {}, []
    by_name, errors = await _batched(client, variables, headers, url, "unit")
    if errors and not by_name:
        return {}, errors
    out: dict[str, str | None] = {}
    for v in variables:
        if v.name in by_name:
            out[v.name] = normalize_unit(by_name[v.name].get("unit_of_measure"))
        else:
            errors.append({"name": v.name, "kind": "unit", "message": "no result returned"})
    return out, errors


async def _batched_with_status(
    client: httpx.AsyncClient,
    variables: list[Variable],
    headers: dict[str, str],
    url: str,
    kind: str,
    extract: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Roles, functions and measures: batched call, per-row ``status``, ``extract(row)`` -> value.
    ``extract`` returning ``None`` means the row carried nothing usable and is reported as an error."""
    if not variables:
        return {}, []
    by_name, errors = await _batched(client, variables, headers, url, kind)
    if errors and not by_name:
        return {}, errors
    out: dict[str, Any] = {}
    for v in variables:
        row = by_name.get(v.name)
        if row is None:
            errors.append({"name": v.name, "kind": kind, "message": "no result returned"})
        elif str(row.get("status", "ok")).lower() not in ("ok", "success", ""):
            errors.append({"name": v.name, "kind": kind, "message": f"n8n status {row.get('status')!r}"})
        else:
            value = extract(row)
            if value is None:
                errors.append({"name": v.name, "kind": kind, "message": "no usable value in result"})
            else:
                out[v.name] = value
    return out, errors


async def suggest_roles(
    client: httpx.AsyncClient, variables: list[Variable], headers: dict[str, str], url: str
) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    return await _batched_with_status(client, variables, headers, url, "role", role_from_result)


async def suggest_functions(
    client: httpx.AsyncClient, variables: list[Variable], headers: dict[str, str], url: str
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """``functions_from_result`` gives ``None`` when the row has no function key at all;
    treat that as "none applies" since an empty list is the workflow's normal answer."""
    return await _batched_with_status(
        client, variables, headers, url, "function", lambda row: functions_from_result(row) or []
    )


async def suggest_measures(
    client: httpx.AsyncClient, variables: list[Variable], headers: dict[str, str], url: str
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    return await _batched_with_status(
        client, variables, headers, url, "measure", measure_from_result
    )


async def suggest_concepts(
    client: httpx.AsyncClient, variables: list[Variable], headers: dict[str, str], url: str, concurrency: int
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, Any]]]:
    sem = asyncio.Semaphore(max(1, concurrency))
    out: dict[str, list[dict[str, str]]] = {}
    errors: list[dict[str, Any]] = []

    async def one(v: Variable) -> None:
        async with sem:
            last = ""
            for attempt in range(ATTEMPTS):
                try:
                    data = await _post(client, url, {"variables": [variable_input(v)]}, headers)
                except EnrichError as exc:
                    errors.append({"name": v.name, "kind": "concept", "message": str(exc)})
                    return
                rows = [r for r in data.get("results", []) if isinstance(r, dict)]
                hit = next((r for r in rows if r.get("variable_name") == v.name), None)
                if hit is not None:
                    out[v.name] = normalize_concepts(hit.get("elsst_concepts"))
                    return
                last = "empty or mismatched result"  # the n8n loop bug; retry
                if attempt < ATTEMPTS - 1:
                    await asyncio.sleep(BACKOFF * (attempt + 1))
            errors.append({"name": v.name, "kind": "concept", "message": last})

    await asyncio.gather(*(one(v) for v in variables))
    return out, errors


async def enrich(
    variables: list[Variable],
    kinds: Iterable[str] = KINDS,
    *,
    client: httpx.AsyncClient | None = None,
) -> EnrichResult:
    """Ask n8n for unit, concept, role, function and/or measure suggestions. Raises ``NotConfigured`` without a key."""
    if not settings.n8n_bearer_key:
        raise NotConfigured("AI enrichment is not configured (set DDI_N8N_BEARER_KEY)")
    kinds = set(kinds)
    headers = {"Authorization": settings.n8n_bearer_key}
    result = EnrichResult()
    own = client is None
    client = client or httpx.AsyncClient(timeout=settings.n8n_timeout)
    try:
        tasks = []
        if "unit" in kinds:
            tasks.append(suggest_units(client, variables, headers, settings.n8n_unit_url))
        if "concept" in kinds:
            tasks.append(
                suggest_concepts(client, variables, headers, settings.n8n_concept_url, settings.n8n_concurrency)
            )
        if "role" in kinds:
            tasks.append(suggest_roles(client, variables, headers, settings.n8n_role_url))
        if "function" in kinds:
            tasks.append(suggest_functions(client, variables, headers, settings.n8n_function_url))
        if "measure" in kinds:
            tasks.append(suggest_measures(client, variables, headers, settings.n8n_measure_url))
        outcomes = await asyncio.gather(*tasks)
    finally:
        if own:
            await client.aclose()
    keys = [k for k in KINDS if k in kinds]
    for key, (values, errors) in zip(keys, outcomes):
        field_name = FIELD_BY_KIND[key]
        for name, value in values.items():
            result.suggestions.setdefault(name, {"name": name})[field_name] = value
        result.errors.extend(errors)
    return result
