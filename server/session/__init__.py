"""Session management for ACS WebSocket connections."""

__all__ = ["SessionPipeline", "Session", "SessionManager"]


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
    raise AttributeError(name)
