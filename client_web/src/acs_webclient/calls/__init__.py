"""
Calls submodule for managing multi-participant voice translation calls.

Public API:
- CallManager: Main entry point for managing calls
- CallState: Individual call state (for type hints)
"""

from .call_manager import CallManager
from .call_state import CallState

__all__ = ["CallManager", "CallState"]
