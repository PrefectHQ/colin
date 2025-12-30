"""Colin - A context engine for the AI era."""

try:
    from importlib.metadata import version

    __version__ = version("colin")
except Exception:
    __version__ = "0.0.0+dev"

import colin.settings as _settings
from colin import api

settings = _settings.ColinSettings()

__all__ = [
    "__version__",
    "api",
    "settings",
]
