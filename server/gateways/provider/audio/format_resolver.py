from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ....audio import AudioFormat


@dataclass
class AcsFormatResolver:
    """Resolves target ACS audio format and frame_bytes from session metadata."""

    session_metadata: Dict[str, Any]

    def get_target_format(self) -> AudioFormat:
        return self._audio_format_from_dict(self._target_format_dict())

    def get_frame_bytes(self, fmt: AudioFormat | None = None) -> int:
        target_format = fmt or self.get_target_format()
        frame_bytes = self._frame_bytes_from_metadata(target_format)
        # persist sanitized frame_bytes back into metadata
        acs_audio = self.session_metadata.get("acs_audio") if isinstance(self.session_metadata, dict) else None
        fmt_block = acs_audio.get("format") if isinstance(acs_audio, dict) else None
        if isinstance(fmt_block, dict):
            fmt_block["frame_bytes"] = frame_bytes
        return frame_bytes

    def _target_format_dict(self) -> Dict[str, Any]:
        fmt: Dict[str, Any] = {"encoding": "pcm16", "sample_rate_hz": 16000, "channels": 1}
        acs_audio = self.session_metadata.get("acs_audio") if isinstance(self.session_metadata, dict) else None
        meta_fmt = acs_audio.get("format") if isinstance(acs_audio, dict) else None
        if isinstance(meta_fmt, dict):
            fmt.update({k: v for k, v in meta_fmt.items() if v is not None})
        return fmt

    def _frame_bytes_from_metadata(self, fmt: AudioFormat) -> int:
        acs_audio = self.session_metadata.get("acs_audio") if isinstance(self.session_metadata, dict) else None
        meta_fmt = acs_audio.get("format") if isinstance(acs_audio, dict) else None
        frame_bytes = self._sanitize_frame_bytes((meta_fmt or {}).get("frame_bytes"), fmt)
        if frame_bytes <= 0:
            frame_bytes = int(fmt.sample_rate_hz * self._frame_ms() / 1000) * fmt.bytes_per_frame()
        return self._sanitize_frame_bytes(frame_bytes, fmt)

    def _frame_ms(self) -> int:
        return 20

    def _audio_format_from_dict(self, data: Dict[str, Any]) -> AudioFormat:
        sample_rate = int(data.get("sample_rate_hz") or data.get("sampleRateHz") or 16000)
        channels = int(data.get("channels") or 1)
        raw_sample_format = data.get("encoding") or data.get("sample_format") or "pcm16"
        sample_format = str(raw_sample_format).lower()
        if sample_format.startswith("pcm"):
            sample_format = "pcm16"
        return AudioFormat(sample_rate_hz=sample_rate, channels=channels, sample_format=sample_format)

    def _sanitize_frame_bytes(self, frame_bytes: Any, fmt: AudioFormat) -> int:
        try:
            value = int(frame_bytes)
        except (TypeError, ValueError):
            return 0
        if value <= 0:
            return 0
        frame_size = fmt.bytes_per_frame()
        if value < frame_size:
            return frame_size
        remainder = value % frame_size
        return value if remainder == 0 else value - remainder


class ProviderFormatResolver:
    """Resolves provider source audio format for a given event."""

    def resolve(self, event: Dict[str, Any], target_format: AudioFormat) -> AudioFormat:
        format_info: Dict[str, Any] = {"encoding": None, "sample_rate_hz": None, "channels": None, "sample_format": None}
        payload = event.payload if hasattr(event, "payload") else {}
        payload_format = payload.get("format") if isinstance(payload, dict) else None
        if isinstance(payload_format, dict):
            format_info.update({k: v for k, v in payload_format.items() if v is not None})

        if format_info.get("sample_rate_hz") is None:
            format_info["sample_rate_hz"] = target_format.sample_rate_hz
        if format_info.get("channels") is None:
            format_info["channels"] = target_format.channels
        if format_info.get("encoding") is None and format_info.get("sample_format") is None:
            format_info["encoding"] = target_format.sample_format

        return AcsFormatResolver({})._audio_format_from_dict(format_info)
