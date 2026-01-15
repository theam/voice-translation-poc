from __future__ import annotations

from ....models.provider_events import ProviderOutputEvent


class StreamKeyBuilder:
    """Creates stable keys for per-stream audio state."""

    def build(self, event: ProviderOutputEvent) -> str:
        participant = event.participant_id or "unknown"
        stream = event.stream_id or event.commit_id or "stream"
        return f"{event.session_id}:{participant}:{stream}"
