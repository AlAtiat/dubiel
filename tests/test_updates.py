"""Version comparison logic for the in-app "Check for Updates" feature."""
from dubiel import updates


def test_parse_version_tolerates_v_prefix_and_suffix():
    assert updates.parse_version("v1.2.3-rc1") == (1, 2, 3)
    assert updates.parse_version("0.0.1") == (0, 0, 1)
    assert updates.parse_version("") == ()
    assert updates.parse_version("not-a-version") == ()


def test_is_newer():
    assert updates.is_newer("v2.0.0", "1.9.9") is True
    assert updates.is_newer("v1.0.0", "1.0.0") is False
    assert updates.is_newer("v0.9.0", "1.0.0") is False
    assert updates.is_newer("not-a-version", "1.0.0") is False


def test_current_version_falls_back_to_dev_when_unpackaged():
    # dubiel isn't pip-installed in the test environment -> PackageNotFoundError path.
    assert updates.current_version() == "dev"
