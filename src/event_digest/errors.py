"""JSON-safe rendering of validation errors.

Validation errors echo the rejected value as "input". Python's JSON parser
accepts NaN/Infinity literals and overflows numbers such as 1e400 to
infinity, but non-finite floats cannot be written to a JSON response.
Without sanitizing, a correctly rejected request would fail with 500.
"""

import math

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def make_json_safe(value: object) -> object:
    """Replace non-finite floats with strings ("nan", "inf", "-inf").

    Dicts and lists are processed recursively; all other values, including
    finite numbers, are returned unchanged.
    """

    if isinstance(value, float) and not math.isfinite(value):
        return str(value)

    if isinstance(value, dict):
        return {
            key: make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            make_json_safe(item)
            for item in value
        ]

    return value


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """FastAPI's default request-validation handler, made JSON-safe."""

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": make_json_safe(
                jsonable_encoder(exc.errors())
            ),
        },
    )
