"""Type mappings shared by the DDI-CDI generator."""

from __future__ import annotations

XSD = "https://www.w3.org/TR/xmlschema-2/#"

_XSD_TYPES = {
    "int8": "byte", "int16": "short", "int32": "int", "int64": "long", "int": "int", "integer": "integer",
    "uint8": "unsignedByte", "uint16": "unsignedShort", "uint32": "unsignedInt", "uint64": "unsignedLong",
    "float": "float", "float32": "float", "float64": "double", "double": "double",
    "decimal": "decimal", "numeric": "decimal", "number": "decimal", "complex": "string",
    "string": "string", "str": "string", "object": "string", "text": "string", "varchar": "string",
    "character": "string", "char": "string",
    "datetime": "dateTime", "datetime64": "dateTime", "timestamp": "dateTime", "date": "date",
    "time": "time", "timedelta": "duration", "duration": "duration",
    "bool": "boolean", "boolean": "boolean",
    "category": "string", "factor": "string", "array": "string", "list": "string", "unknown": "string",
}


def map_to_xsd_type(storage_type: str) -> str:
    """Map a readstat/CSV storage type to an XSD type URI (same rules as the original app)."""
    t = str(storage_type).lower()
    if "int" in t:
        return XSD + "int"
    if "float" in t:
        return XSD + "double"
    if "date" in t:
        return XSD + "dateTime"
    if "bool" in t:
        return XSD + "boolean"
    return XSD + _XSD_TYPES.get(t, "string")


_CLASSIFICATION = {"nominal": "Nominal", "scale": "Continuous", "ordinal": "Ordinal", "unknown": "Nominal"}


def classification_level(measure: str) -> str:
    return _CLASSIFICATION.get((measure or "unknown").lower(), "Nominal")
