from __future__ import annotations

from dataclasses import dataclass

from ....audio import AudioFormat, PcmConverter, UnsupportedAudioFormatError
from .errors import AudioTranscodingError


@dataclass
class AudioTranscoder:
    """Converts provider audio to ACS target format."""

    converter: PcmConverter

    def transcode(self, audio_bytes: bytes, source_format: AudioFormat, target_format: AudioFormat) -> bytes:
        if source_format == target_format:
            return audio_bytes
        try:
            return self.converter.convert(audio_bytes, source_format, target_format)
        except UnsupportedAudioFormatError as exc:
            raise AudioTranscodingError(str(exc)) from exc
        except Exception as exc:
            raise AudioTranscodingError("conversion_failed") from exc
