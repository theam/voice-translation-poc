from __future__ import annotations

import logging
from typing import Any, Dict

from ...models.envelope import Envelope

logger = logging.getLogger(__name__)


class AudioMetadataHandler:
    """
    Handles ACS AudioMetadata messages (strict to current ACS payload shape).

    Expected ACS payload in envelope.payload:
      {
        "audioMetadata": {
          "subscriptionId": "...",
          "encoding": "PCM",
          "sampleRate": 16000,
          "channels": 1,
          "length": 640
        }
      }

    Stores a canonical format record in session_metadata for later use
    (e.g., AudioData handling, resampling/adaptation for translation providers).
    """

    SESSION_KEY = "acs_audio"

    def __init__(self, session_metadata: Dict[str, Any]):
        self.session_metadata = session_metadata

    async def handle(self, envelope: Envelope) -> None:
        logger.info("Handling AudioMetadata: %s (session=%s)", envelope.message_id, envelope.session_id)

        payload = envelope.payload or {}
        meta = payload.get("audioMetadata")

        if not isinstance(meta, dict):
            logger.warning(
                "Expected payload.audioMetadata dict not found (message_id=%s, type=%s, keys=%s)",
                envelope.message_id,
                envelope.type,
                list(payload.keys()),
            )
            return

        # Extract exactly what we need later (no validation here)
        stream_format = {
            "source": "acs",
            "subscription_id": meta.get("subscriptionId"),
            "encoding": meta.get("encoding"),          # e.g., "PCM"
            "sample_rate_hz": meta.get("sampleRate"),  # e.g., 16000
            "channels": meta.get("channels"),          # e.g., 1
            "frame_bytes": meta.get("length"),         # bytes per frame (often 20ms)
            # PCM defaults: keep this as a convenient downstream hint
            "bits_per_sample": 16,
        }

        state = self.session_metadata.setdefault(self.SESSION_KEY, {})
        state["format"] = stream_format
        state["audio_ready"] = True
        state["metadata_message_id"] = envelope.message_id
        state["metadata_received_at_utc"] = envelope.timestamp_utc

        logger.info(
            "Stored ACS audio metadata (session=%s): sub=%s enc=%s sr=%s ch=%s frame_bytes=%s",
            envelope.session_id,
            stream_format.get("subscription_id"),
            stream_format.get("encoding"),
            stream_format.get("sample_rate_hz"),
            stream_format.get("channels"),
            stream_format.get("frame_bytes"),
        )
