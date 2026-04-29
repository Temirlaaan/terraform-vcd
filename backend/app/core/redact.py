"""Sensitive-string redaction for terraform stdout/stderr.

Applied at two points:
  - On Operation row insert/update via SQLAlchemy event hook (redacts
    ``error_message`` and ``plan_output`` before they hit the database).
  - On WebSocket pub/sub line emission in ``tf_runner._read_stream`` so
    live stream subscribers see the same redacted text as the at-rest DB.

Patterns target tokens that may legitimately appear in terraform errors:
  - AWS credential env-var prints (``AWS_ACCESS_KEY_ID=...``).
  - Generic ``password=...`` / ``secret=...`` query / form pairs.
  - Bearer authorization headers.
  - URLs with embedded basic-auth (``https://user:pass@host``).

The redaction is intentionally conservative — false-positive redactions
are preferred over leaking a live credential.
"""

from __future__ import annotations

import re
from typing import Pattern


_REDACT_TOKEN = "***REDACTED***"


_PATTERNS: list[tuple[Pattern[str], str]] = [
    # AWS_ACCESS_KEY_ID=AKIA..., AWS_SECRET_ACCESS_KEY=...
    (
        re.compile(r"(AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN))\s*=\s*\S+", re.IGNORECASE),
        rf"\1={_REDACT_TOKEN}",
    ),
    # password=... / passwd=... / secret=... in query strings or env dumps
    (
        re.compile(r"((?:password|passwd|secret|api_token|api_key|token)\s*[=:]\s*)([^\s&'\"]+)", re.IGNORECASE),
        rf"\1{_REDACT_TOKEN}",
    ),
    # Bearer <jwt>
    (
        re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
        rf"\1{_REDACT_TOKEN}",
    ),
    # https://user:pass@host
    (
        re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@"),
        rf"\1{_REDACT_TOKEN}@",
    ),
]


def redact(text: str | None) -> str | None:
    """Return *text* with sensitive substrings replaced by ``***REDACTED***``.

    Returns ``None`` unchanged so callers can pass nullable columns through.
    """
    if not text:
        return text
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out
