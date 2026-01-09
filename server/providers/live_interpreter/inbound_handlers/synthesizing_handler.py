from __future__ import annotations

import logging
from typing import Optional

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class SynthesizingHandler:
    """Handle synthesizing events to extract audio data and publish."""

    def __init__(self, publish_audio: callable):
        """
        Initialize handler with audio publisher.

        Args:
            publish_audio: Function to publish synthesized audio
        """
        self._publish_audio = publish_audio

    @staticmethod
    def _strip_wav_header(audio_data: bytes) -> bytes:
        """
        Strip WAV header if present in audio data.

        Azure Speech SDK may include a 44-byte WAV header at the start of synthesized audio.
        WAV header starts with 'RIFF' magic bytes.

        Args:
            audio_data: Raw audio bytes (may include WAV header)

        Returns:
            Raw PCM audio bytes without header
        """
        # Check for WAV header (RIFF magic bytes)
        if len(audio_data) > 44 and audio_data[:4] == b'RIFF':
            logger.info("🔧 WAV header detected - stripping 44 bytes")
            # Log first few bytes for debugging
            logger.debug(f"First 8 bytes before strip: {audio_data[:8].hex()}")
            pcm_data = audio_data[44:]
            logger.debug(f"First 8 bytes after strip: {pcm_data[:8].hex()}")
            return pcm_data

        # Log if no header detected
        logger.info(f"ℹ️ No WAV header detected. First 4 bytes: {audio_data[:4].hex() if len(audio_data) >= 4 else 'N/A'}")
        return audio_data

    def __call__(self, evt: speechsdk.translation.TranslationSynthesisEventArgs) -> None:
        """
        Handle synthesizing callback - extract audio and publish.

        Args:
            evt: Synthesis event from Speech SDK
        """
        logger.info("🎵 Synthesizing callback triggered!")

        try:
            if not evt or not getattr(evt, "result", None):
                logger.warning("⚠️ Received empty synthesis event")
                return

            # Use evt.result.audio (not audio_data) - this is the correct property
            audio_data = evt.result.audio if hasattr(evt.result, "audio") else None
            if not audio_data:
                logger.warning("⚠️ Synthesis event has no audio data")
                return

            logger.info(f"✅ Received {len(audio_data)} bytes of synthesized audio (before header strip)")

            # Strip WAV header if present
            pcm_data = self._strip_wav_header(audio_data)

            if pcm_data:
                logger.info(f"🎵 Got synthesized audio: {len(pcm_data)} bytes")
                self._publish_audio(pcm_data, True)  # partial=True
            else:
                logger.warning("⚠️ Synthesizing callback fired but no audio bytes returned")

        except Exception as exc:
            logger.error(f"❌ Synthesizing callback error: {exc}", exc_info=True)
