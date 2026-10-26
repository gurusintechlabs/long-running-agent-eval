"""The HTTP error model: ``ApiError`` and how an error becomes a response body.

Messages are written for clients: never a stack trace, a file system path or a secret. A 500 always
carries the same generic text; the details go to the server log only.
"""
from __future__ import annotations

TYPES = {400: "BadRequest", 401: "Unauthorized", 403: "Forbidden", 404: "NotFound",
         405: "MethodNotAllowed", 409: "Conflict", 411: "LengthRequired", 413: "PayloadTooLarge",
         500: "InternalError"}
INTERNAL_MESSAGE = "internal error"


class ApiError(Exception):
    def __init__(self, status: int, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status if status in TYPES else 400
        self.message = message
        self.headers = dict(headers or {})


def bad_request(message: str) -> ApiError:
    return ApiError(400, message)


def not_found(what: str = "not found") -> ApiError:
    return ApiError(404, what)


def error_body(status: int, message: str, path: str) -> tuple[str, dict]:
    """``(content type, body)`` of an error response."""
    if status == 500:
        message = INTERNAL_MESSAGE
    return "application/json", {"error": {"type": TYPES.get(status, "BadRequest"), "message": message}}
