from __future__ import annotations

import logging
from typing import Optional

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class SynthesizingHandler:
    """Handle synthesizing events to extract audio data from translation synthesis."""

    def handle(
        self, evt: speechsdk.translation.TranslationSynthesisEventArgs
    ) -> Optional[bytes]:
        """
        Process synthesizing event and return PCM audio bytes.

        Args:
            evt: Synthesis event from Speech SDK

        Returns:
            Raw PCM audio bytes, or None if unavailable
        """
        logger.info("🎵 Received synthesized audio event")
        if not evt or not getattr(evt, "result", None):
            logger.warning("⚠️ Received empty synthesis event")
            return None

        # Use evt.result.audio (not audio_data) - this is the correct property
        audio_data = evt.result.audio if hasattr(evt.result, "audio") else None
        if not audio_data:
            logger.warning("⚠️ Synthesis event has no audio data")
            return None

        logger.info(f"✅ Received {len(audio_data)} bytes of synthesized audio")
        return audio_data
