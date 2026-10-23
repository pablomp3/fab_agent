from __future__ import annotations

from enum import StrEnum
from typing import cast

from pydantic import ValidationError


class ValidationDetail(StrEnum):
    MALFORMED_JSON = "malformed_json"
    MISSING_FIELD = "missing_field"
    EXTRA_FIELD = "extra_field"
    WRONG_TYPE = "wrong_type"
    INVALID_ENUM = "invalid_enum"
    CONSTRAINT_VIOLATION = "constraint_violation"
    INVALID_VALUE = "invalid_value"


class FinishReasonDetail(StrEnum):
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    FUNCTION_CALL = "function_call"
    OTHER = "other"


def sanitized_finish_reason(reason: str) -> FinishReasonDetail:
    try:
        return FinishReasonDetail(reason)
    except ValueError:
        return FinishReasonDetail.OTHER


def _detail(error_type: object) -> ValidationDetail:
    if not isinstance(error_type, str):
        return ValidationDetail.INVALID_VALUE
    if error_type == "json_invalid":
        return ValidationDetail.MALFORMED_JSON
    if error_type == "missing":
        return ValidationDetail.MISSING_FIELD
    if error_type == "extra_forbidden":
        return ValidationDetail.EXTRA_FIELD
    if error_type in {"enum", "literal_error"}:
        return ValidationDetail.INVALID_ENUM
    if error_type.endswith("_type"):
        return ValidationDetail.WRONG_TYPE
    if error_type in {"too_short", "too_long", "greater_than", "less_than"}:
        return ValidationDetail.CONSTRAINT_VIOLATION
    return ValidationDetail.INVALID_VALUE


def _details_from_objects(error_objects: object) -> tuple[ValidationDetail, ...]:
    if not isinstance(error_objects, list):
        return (ValidationDetail.INVALID_VALUE,)
    details: list[ValidationDetail] = []
    for error_object in cast(list[object], error_objects):
        if not isinstance(error_object, dict):
            continue
        raw_error = cast(dict[object, object], error_object)
        detail = _detail(raw_error.get("type"))
        if detail not in details:
            details.append(detail)
        if len(details) == len(ValidationDetail):
            break
    return tuple(details) or (ValidationDetail.INVALID_VALUE,)


def sanitized_validation_details(
    error: ValidationError,
) -> tuple[ValidationDetail, ...]:
    """Map Pydantic errors to fixed labels without reading inputs or locations."""
    errors = error.errors(include_input=False, include_context=False, include_url=False)
    return _details_from_objects(errors)
