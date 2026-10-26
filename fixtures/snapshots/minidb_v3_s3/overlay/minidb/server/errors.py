"""The HTTP error model: ``ApiError`` and how an error becomes a response body.

Since CR-3 every error is an RFC 9457 problem document (``application/problem+json``):
``{"type": "https://minidb.dev/problems/<slug>", "title", "status", "detail", "instance"}``.
Details are written for clients: never a stack trace, a file system path, an internal SQL error or a
secret. A 500 always carries the same generic text; the details go to the server log only.
"""
from __future__ import annotations

PROBLEM_BASE = "https://minidb.dev/problems/"
PROBLEMS = {400: ("bad-request", "Bad Request"), 401: ("unauthorized", "Unauthorized"),
            403: ("forbidden", "Forbidden"), 404: ("not-found", "Not Found"),
            405: ("method-not-allowed", "Method Not Allowed"), 409: ("conflict", "Conflict"),
            411: ("length-required", "Length Required"), 413: ("payload-too-large", "Payload Too Large"),
            429: ("too-many-requests", "Too Many Requests"), 500: ("internal-error", "Internal Server Error"),
            502: ("bad-gateway", "Bad Gateway"), 503: ("unavailable", "Service Unavailable")}
TYPES = PROBLEMS
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
    slug, title = PROBLEMS.get(status, PROBLEMS[400])
    return "application/problem+json", {"type": PROBLEM_BASE + slug, "title": title, "status": status,
                                        "detail": message, "instance": path}
