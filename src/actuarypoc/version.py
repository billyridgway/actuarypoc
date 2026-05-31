from __future__ import annotations

"""Version helpers for the projection engine.

This module centralises how we derive a stable ``engine_version`` string so
that AuditRecord, lightweight audit payloads, and any future consumers all
agree on the same value.

Precedence (highest → lowest):

1. ``ENGINE_VERSION`` env var
2. ``ILLUSTRATION_ENGINE_VERSION`` env var
3. Installed package metadata for ``actuarypoc``
4. Fallback constant matching ``pyproject.toml``

In operator‑driven runs we typically set ``ILLUSTRATION_ENGINE_VERSION`` on
the Job, but the helpers are defensive so local/unit usage works without
extra configuration.
"""

import os
from importlib.metadata import PackageNotFoundError, version as pkg_version


_FALLBACK_ENGINE_VERSION = "0.1.0"  # Keep in sync with pyproject.toml


def get_engine_version() -> str:
    """Return a best-effort engine version string.

    Never raises; always returns a non-empty string suitable for audit
    metadata. Env vars take precedence so operators can override without
    rebuilding images.
    """

    # Explicit overrides first so operators can pin engine version.
    env_version = os.getenv("ENGINE_VERSION") or os.getenv("ILLUSTRATION_ENGINE_VERSION")
    if env_version:
        return env_version

    # Try to read from installed package metadata when available.
    try:
        return pkg_version("actuarypoc")
    except PackageNotFoundError:
        return _FALLBACK_ENGINE_VERSION
    except Exception:
        # Extremely defensive: never let version lookups break callers.
        return _FALLBACK_ENGINE_VERSION

