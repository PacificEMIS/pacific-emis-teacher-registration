"""
Project-wide pytest fixtures.

App-specific fixtures and factories live in each app's tests/ package.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_media_root(settings, tmp_path):
    """Every test writes uploaded files to its own temporary directory."""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir()
