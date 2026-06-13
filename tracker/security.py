"""Keep secrets out of logs and crash output.

The Travelpayouts token and SerpApi key travel in URL query strings, so any
exception that echoes a request URL (httpx does) would otherwise leak the key
into GitHub Actions logs. `redact()` scrubs both the literal secret values and
common secret-bearing patterns; `safe_print()` is a drop-in for `print()`.
"""
from __future__ import annotations

import os
import re

# Env vars whose literal values must never appear in output.
SECRET_ENV_VARS = (
    "TRAVELPAYOUTS_TOKEN",
    "SERPAPI_KEY",
    "DATABASE_URL",
)

_MASK = "***REDACTED***"

# Pattern-based scrubs for secrets embedded in URLs/strings, even if the exact
# env value isn't known here (e.g. a password inside a connection string).
_PATTERNS = (
    re.compile(r"(?i)(token=)[^&\s'\"]+"),
    re.compile(r"(?i)(api_key=)[^&\s'\"]+"),
    re.compile(r"(?i)(apikey=)[^&\s'\"]+"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(://[^:/@\s]+:)[^@/\s]+(@)"),  # user:password@ in a URL
)


def _secret_values() -> list[str]:
    out: list[str] = []
    for key in SECRET_ENV_VARS:
        val = os.getenv(key)
        if val:
            out.append(val)
            # Also mask the password component of a DB URL on its own.
            m = re.search(r"://[^:/@\s]+:([^@/\s]+)@", val)
            if m:
                out.append(m.group(1))
    return out


def redact(value: object) -> str:
    """Return str(value) with known secrets and secret-shaped patterns masked."""
    text = str(value)
    for secret in _secret_values():
        if secret and secret in text:
            text = text.replace(secret, _MASK)
    for pat in _PATTERNS:
        text = pat.sub(lambda m: m.group(1) + _MASK + (m.group(2) if m.lastindex and m.lastindex >= 2 else ""), text)
    return text


def safe_print(*args: object) -> None:
    """print(), but every argument is redacted first."""
    print(*(redact(a) for a in args))


def require_secrets(*names: str) -> None:
    """Raise if a required secret is missing or still a placeholder.

    Fails fast and loudly *without* printing the value itself.
    """
    missing = []
    for name in names:
        val = os.getenv(name, "")
        if not val or "PASTE_" in val or "YOUR-" in val.upper():
            missing.append(name)
    if missing:
        raise RuntimeError(f"Missing/placeholder required secrets: {', '.join(missing)}")
