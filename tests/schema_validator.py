"""Shared stdlib JSON Schema mini-validator for tests.

Moved out of test_render_model.py so render-model tests and schema tests
validate with one implementation. Supports exactly these keywords:
type, enum, const, required, properties, additionalProperties, items,
minItems/maxItems, minLength, minimum/maximum, pattern, and
format: date-time. Any other keyword (oneOf, anyOf, $ref, maxLength,
format: uri/date, ...) is NOT validated — a schema using them would
silently false-validate — so the helper is only sound for schemas whose
keywords stay within the supported set (render_model, run_manifest,
source). No jsonschema package; stdlib only.
"""
import json
import re
from datetime import datetime


def _is_type(value, name):
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "null":
        return value is None
    return False


_DATETIME_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _is_iso_datetime(value):
    """A JSON Schema date-time needs a time component: an
    extended-format date+time prefix (YYYY-MM-DD then T or space then
    HH:MM) must be present, and datetime.fromisoformat must parse the
    string; a trailing Z is accepted as +00:00. Timezone offset not
    required (date-time, not RFC 3339-strict)."""
    if not _DATETIME_PREFIX_RE.search(value):
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def schema_errors(schema, value, path="$"):
    """Return a list of human-readable validation errors (empty = valid)."""
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")
    t = schema.get("type")
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(_is_type(value, n) for n in names):
            errors.append(f"{path}: expected type {names}, got {type(value).__name__}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errors += schema_errors(sub, value[key], f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unexpected '{key}'")
    if isinstance(value, list):
        if "items" in schema:
            for i, item in enumerate(value):
                errors += schema_errors(schema["items"], item, f"{path}[{i}]")
        lo, hi = schema.get("minItems"), schema.get("maxItems")
        if lo is not None and len(value) < lo:
            errors.append(f"{path}: fewer than {lo} items")
        if hi is not None and len(value) > hi:
            errors.append(f"{path}: more than {hi} items")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(
                f"{path}: {value!r} does not match pattern {schema['pattern']!r}"
            )
        if schema.get("format") == "date-time" and not _is_iso_datetime(value):
            errors.append(f"{path}: {value!r} is not an ISO 8601 date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if lo is not None and value < lo:
            errors.append(f"{path}: below minimum {lo}")
        if hi is not None and value > hi:
            errors.append(f"{path}: above maximum {hi}")
    return errors


def load_schema(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
