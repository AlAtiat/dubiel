"""Lightweight update check against the project's GitHub Releases.

Manual-only: nothing here runs automatically. The GUI calls ``fetch_latest_release``
from a background thread when the user clicks "Check for Updates", then compares the
result against ``current_version`` with ``is_newer``.

Standard-library only (urllib + json) — no third-party dependencies, no API token.
The unauthenticated GitHub API allows 60 requests/hour/IP, which is ample for an
on-demand check.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from importlib.metadata import PackageNotFoundError, version as _pkg_version

GITHUB_REPO = "AlAtiat/dubiel"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"

_TIMEOUT_SECONDS = 5.0


def current_version() -> str:
    """Return the installed package version, or ``"dev"`` when unpackaged.

    Read here (rather than importing ``__version__`` from the package) to avoid the
    ``__init__`` -> ``app`` -> ``updates`` import cycle.
    """
    try:
        return _pkg_version("dubiel")
    except PackageNotFoundError:
        return "dev"


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a version/tag string into a tuple of leading integers for comparison.

    Tolerates a leading ``v`` and pre-release suffixes, e.g. ``"v1.2.3-rc1"`` -> ``(1, 2, 3)``.
    Unparseable input yields ``()`` (treated as the oldest possible version).
    """
    cleaned = value.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(latest_tag: str, current: str) -> bool:
    """True when ``latest_tag`` is a strictly newer version than ``current``."""
    latest = parse_version(latest_tag)
    cur = parse_version(current)
    if not latest:
        return False
    return latest > cur


def fetch_latest_release() -> dict | None:
    """GET the latest GitHub release, or ``None`` on any network/parse error.

    Returns the parsed JSON dict (keys include ``tag_name`` and ``html_url``).
    Never raises — callers treat ``None`` as "couldn't check".
    """
    req = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "dubiel-update-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def demo() -> None:
    assert parse_version("v1.2.3-rc1") == (1, 2, 3)
    assert parse_version("") == ()
    assert is_newer("v2.0.0", "1.9.9") is True
    assert is_newer("v1.0.0", "1.0.0") is False
    assert is_newer("not-a-version", "1.0.0") is False
    assert current_version() == "dev" or parse_version(current_version())
    print("updates.py self-check OK")


if __name__ == "__main__":
    demo()
