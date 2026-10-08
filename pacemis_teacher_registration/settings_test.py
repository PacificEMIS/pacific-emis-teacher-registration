"""
Settings used exclusively by the automated test suite (see pyproject.toml,
[tool.pytest.ini_options]). Never point a running server at this module.

Imports the regular settings, then overrides anything that would otherwise
touch the outside world: email, uploaded files, the EMIS API, and slow
password hashing.
"""

import tempfile
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# manage.py loads .env before settings are imported; pytest does not go through
# manage.py, so load it here so the local database credentials are available.
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path if _env_path.exists() else find_dotenv())

from .settings import *  # noqa: E402, F401, F403

# Never send real email from tests. pytest-django also forces this, but be
# explicit so running tests through manage.py behaves the same way.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Uploaded files go to a throwaway directory, never the project media/ folder.
# conftest.py additionally gives every test its own fresh directory.
MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="pacemis-test-media-"))

# Make sure no test can reach a real EMIS instance, even if .env points at one.
EMIS = {
    **EMIS,  # noqa: F405
    "BASE_URL": "https://emis.invalid",
    "USERNAME": "test-user",
    "PASSWORD": "test-password",
    "TIMEOUT_SECONDS": 1,
    "MAX_RETRIES": 1,
}
EMIS["LOGIN_URL"] = f'{EMIS["BASE_URL"]}/api/token'
EMIS["LOOKUPS_URL"] = f'{EMIS["BASE_URL"]}/api/lookups/collection/core'

# Fast password hashing makes user creation in tests an order of magnitude cheaper.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Keep logging quiet; tests assert on behaviour, not log output.
LOGGING["root"]["level"] = "WARNING"  # noqa: F405
for _logger in LOGGING["loggers"].values():  # noqa: F405
    _logger["level"] = "WARNING"
