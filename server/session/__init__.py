"""Session management for ACS WebSocket connections."""

__all__ = ["SessionPipeline", "Session", "SessionManager", "InputState", "InputStatus"]


def __getattr__(name):
    if name == "Session":
        from .session import Session  # noqa: WPS433
        return Session
    if name == "SessionManager":
        from .session_manager import SessionManager  # noqa: WPS433
        return SessionManager
    if name == "SessionPipeline":
        from .session_pipeline import SessionPipeline  # noqa: WPS433
        return SessionPipeline
    if name == "InputState":
        from .input_state import InputState  # noqa: WPS433
        return InputState
    if name == "InputStatus":
        from .input_state import InputStatus  # noqa: WPS433
        return InputStatus
    raise AttributeError(name)
