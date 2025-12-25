from __future__ import annotations

import audioop
from dataclasses import dataclass

import numpy as np

from .types import AudioFormat, UnsupportedAudioFormatError


@dataclass
class PcmConverter:
    """PCM16 conversion utilities (mono/stereo + resample)."""

    def convert(self, pcm: bytes, src: AudioFormat, dst: AudioFormat) -> bytes:
        """
        Convert PCM audio from src format to dst format.
        Supports:
          - PCM16 only
          - channels 1 or 2
          - sample rate conversion (resample)
        """
        self._validate_format(src)
        self._validate_format(dst)

        if not pcm:
            return pcm

        working = self._trim_to_frame_boundary(pcm, src)

        if src.channels != dst.channels:
            working = self.to_mono(working, src.channels) if dst.channels == 1 else self.to_stereo(working, src.channels)
            working = self._trim_to_frame_boundary(working, AudioFormat(src.sample_rate_hz, dst.channels, src.sample_format))

        if src.sample_rate_hz != dst.sample_rate_hz:
            working = self.resample_pcm16(working, src.sample_rate_hz, dst.sample_rate_hz, dst.channels)

        return self._trim_to_frame_boundary(working, dst)

    def to_mono(self, pcm16: bytes, src_channels: int) -> bytes:
        """Downmix stereo->mono (no-op if already mono)."""
        if src_channels == 1:
            return pcm16
        if src_channels != 2:
            raise UnsupportedAudioFormatError(f"Unsupported channel count for mono conversion: {src_channels}")
        return audioop.tomono(pcm16, 2, 0.5, 0.5)

    def to_stereo(self, pcm16: bytes, src_channels: int) -> bytes:
        """Upmix mono->stereo by duplication (no-op if already stereo)."""
        if src_channels == 2:
            return pcm16
        if src_channels != 1:
            raise UnsupportedAudioFormatError(f"Unsupported channel count for stereo conversion: {src_channels}")
        return audioop.tostereo(pcm16, 2, 1, 1)

    def resample_pcm16(self, pcm16: bytes, src_rate_hz: int, dst_rate_hz: int, channels: int) -> bytes:
        """
        Resample PCM16 audio.
        Implementation can use:
          - `samplerate` library, or
          - `scipy.signal.resample_poly`, or
          - ffmpeg (last resort for pure-python pipeline)
        """
        if src_rate_hz == dst_rate_hz:
            return pcm16

        frame_bytes = 2 * channels
        trimmed = pcm16[: len(pcm16) - (len(pcm16) % frame_bytes)]
        if not trimmed:
            return b""

        samples = np.frombuffer(trimmed, dtype="<i2").reshape(-1, channels)
        src_length = samples.shape[0]
        target_length = max(1, int(round(src_length * (dst_rate_hz / src_rate_hz))))

        resampled_channels = []
        x_old = np.linspace(0.0, 1.0, num=src_length, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=target_length, endpoint=False)
        for ch in range(channels):
            resampled = np.interp(x_new, x_old, samples[:, ch]).astype(np.int16)
            resampled_channels.append(resampled)

        stacked = np.stack(resampled_channels, axis=1)
        return stacked.astype("<i2").tobytes()

    def rms_pcm16(self, pcm16: bytes, channels: int) -> float:
        """Compute RMS energy of PCM16 (used by barge-in detector and diagnostics)."""
        if not pcm16:
            return 0.0
        frame_bytes = 2 * channels
        trimmed = pcm16[: len(pcm16) - (len(pcm16) % frame_bytes)]
        samples = np.frombuffer(trimmed, dtype="<i2")
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))

    @staticmethod
    def _trim_to_frame_boundary(pcm: bytes, fmt: AudioFormat) -> bytes:
        frame_bytes = fmt.bytes_per_frame()
        remainder = len(pcm) % frame_bytes
        if remainder == 0:
            return pcm
        return pcm[: len(pcm) - remainder]

    @staticmethod
    def _validate_format(fmt: AudioFormat) -> None:
        if fmt.sample_format != "pcm16":
            raise UnsupportedAudioFormatError(f"Unsupported audio format: {fmt.sample_format}")
        if fmt.channels not in (1, 2):
            raise UnsupportedAudioFormatError(f"Unsupported channel count: {fmt.channels}")
