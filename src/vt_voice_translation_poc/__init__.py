"""vt Voice Translation Proof of Concept."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("vt-voice-translation-poc")
except PackageNotFoundError:  # pragma: no cover - fallback during local execution
    __version__ = "0.0.0"

__all__ = ["__version__"]